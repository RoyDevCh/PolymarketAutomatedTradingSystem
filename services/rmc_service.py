"""
Polymarket 微服务入口: RMC (风控中心) + Heartbeat + Phase3

systemd: polymarket-rmc.service
"""

import asyncio
import logging
import os
import time
import signal as sig
import structlog
from pathlib import Path

def _load_proxy():
    proxy_rc = Path.home() / ".proxyrc"
    if proxy_rc.exists():
        for line in proxy_rc.read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export "):]
            if "=" in line and not line.startswith("#"):
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip()
                if key.lower().endswith("_proxy") and val:
                    os.environ.setdefault(key, val)

_load_proxy()

from core.config import CONFIG
from core.rmc import RiskManagementCenter
from core.message_bus import get_bus
from core.heartbeat import telegram_heartbeat_loop
from core.phase3_notify import phase3_notify_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger("rmc_service")


class RMCService:
    """RMC 微服务: 风控 + 心跳 + Phase3 通知 + 队列清理"""
    
    def __init__(self):
        self.bus = get_bus()
        self.rmc = RiskManagementCenter()
        self._running = False
        self._started_at = time.time()
        self._poll_interval = 1.0
    
    async def start(self) -> None:
        logger.info("RMC 微服务启动")
        self._running = True
        pid = os.getpid()
        
        if not self.bus.acquire_lock("rmc", pid):
            logger.error("RMC 服务锁已被占用, 退出")
            return
        
        await self.rmc.init_db()
        
        tasks = [
            asyncio.create_task(self._result_loop(pid), name="rmc_result_consumer"),
            asyncio.create_task(self._maintenance_loop(), name="rmc_maintenance"),
            asyncio.create_task(self._cleanup_loop(pid), name="rmc_cleanup"),
            asyncio.create_task(
                telegram_heartbeat_loop(self._collect_stats, started_at=self._started_at),
                name="telegram_heartbeat",
            ),
            asyncio.create_task(
                phase3_notify_loop(
                    lambda: self.rmc._db,
                    started_at=self._started_at,
                ),
                name="phase3_notify",
            ),
        ]
        
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            logger.info("RMC 服务被取消")
        finally:
            self.bus.release_lock("rmc", pid)
            await self.rmc.close_db()
            logger.info("RMC 服务已关闭")
    
    async def _result_loop(self, pid: int) -> None:
        """消费 OEG 执行结果"""
        while self._running:
            try:
                results = self.bus.poll_results(limit=50, max_age=3600.0)
                
                for result in results:
                    try:
                        await self.rmc.on_trade_signal_from_bus(result)
                    except Exception as e:
                        logger.error("rmc_process_result_error",
                                     signal_id=result.get("signal_id", "?")[:8],
                                     error=str(e))
                
                self.bus.heartbeat("rmc", pid)
                await asyncio.sleep(self._poll_interval if not results else 0.1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("rmc_result_error", error=str(e))
                await asyncio.sleep(2.0)
    
    async def _maintenance_loop(self) -> None:
        """定期维护 (RMC 内部)"""
        try:
            await self.rmc.maintenance_loop()
        except asyncio.CancelledError:
            pass
    
    async def _cleanup_loop(self, pid: int) -> None:
        """定期清理消息队列"""
        while self._running:
            try:
                result = self.bus.cleanup(max_age_hours=24.0)
                if any(v > 0 for v in result.values()):
                    logger.info("queue_cleanup", **result)
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("cleanup_error", error=str(e))
                await asyncio.sleep(300)
    
    async def _collect_stats(self) -> dict:
        """收集心跳统计信息"""
        stats = {
            "rmc": self.rmc.get_process_stats() if hasattr(self.rmc, 'get_process_stats') else {},
            "queue_depth": self.bus.queue_depth(),
            "uptime_hours": (time.time() - self._started_at) / 3600,
        }
        try:
            from core.clob_client import get_collateral_balance_usd, get_clob_client
            client = get_clob_client()
            balance = await asyncio.to_thread(get_collateral_balance_usd, client)
            stats["clob_balance"] = f"${balance:.2f}" if balance is not None else "unavailable"
        except Exception:
            stats["clob_balance"] = "unavailable"
        return stats
    
    async def stop(self) -> None:
        self._running = False


def main():
    service = RMCService()
    asyncio.run(service.start())


if __name__ == "__main__":
    main()
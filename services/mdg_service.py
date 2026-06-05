"""
Polymarket 微服务入口: MDG (市场数据网关)

独立进程运行, 负责发现市场并推送订单簿快照到消息总线。
重启此服务不影响 SPE/OEG/RMC。

systemd: polymarket-mdg.service
"""

import asyncio
import logging
import os
import time
import signal as sig
import structlog
from pathlib import Path

# 代理配置
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
from core.mdg import MarketDataGateway
from core.message_bus import get_bus

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

logger = structlog.get_logger("mdg_service")


class MDGService:
    """MDG 微服务: 发现市场 + 推送订单簿快照到消息总线"""
    
    def __init__(self):
        self.bus = get_bus()
        self.mdg = MarketDataGateway(snapshot_callback=self._on_snapshot)
        self._running = False
        self._started_at = time.time()
        self._snapshot_count = 0
    
    def _on_snapshot(self, snapshot) -> None:
        """将订单簿快照推送到消息总线"""
        import json
        try:
            self._snapshot_count += 1
            if self._snapshot_count <= 5 or self._snapshot_count % 1000 == 0:
                logger.info(
                    "snapshot_pushed",
                    token_id=snapshot.token_id[:16],
                    total=self._snapshot_count,
                )
            self.bus.push_snapshot(
                token_id=snapshot.token_id,
                condition_id=snapshot.condition_id,
                asks_json=json.dumps(
                    [{"price": str(a.price), "size": str(a.size)} for a in snapshot.asks],
                    ensure_ascii=False
                ),
                bids_json=json.dumps(
                    [{"price": str(b.price), "size": str(b.size)} for b in snapshot.bids],
                    ensure_ascii=False
                ),
            )
        except Exception as e:
            logger.error("push_snapshot_error", error=str(e))
    
    async def start(self) -> None:
        logger.info("MDG 微服务启动")
        self._running = True
        pid = os.getpid()
        
        if not self.bus.acquire_lock("mdg", pid):
            logger.error("MDG 服务锁已被占用, 退出")
            return
        
        markets = await self.mdg.discover_markets()
        if not markets:
            logger.error("未发现任何活跃市场")
            self.bus.release_lock("mdg", pid)
            return
        
        logger.info(f"MDG 发现 {len(markets)} 个市场")
        
        tasks = [
            asyncio.create_task(self.mdg.start_market_discovery_loop(), name="mdg_discovery"),
            asyncio.create_task(self._heartbeat_loop(pid), name="mdg_heartbeat"),
        ]
        
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            logger.info("MDG 服务被取消")
        finally:
            self.bus.release_lock("mdg", pid)
            await self.mdg.stop()
            logger.info("MDG 服务已关闭")
    
    async def _heartbeat_loop(self, pid: int) -> None:
        while self._running:
            self.bus.heartbeat("mdg", pid)
            await asyncio.sleep(30)
    
    async def stop(self) -> None:
        self._running = False
        await self.mdg.stop()


def main():
    service = MDGService()
    asyncio.run(service.start())


if __name__ == "__main__":
    main()
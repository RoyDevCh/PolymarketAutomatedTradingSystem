"""
Polymarket 微服务入口: OEG (订单执行网关)

独立进程运行, 从消息总线消费交易信号, 执行下单。

systemd: polymarket-oeg.service
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
from core.oeg import OrderExecutionGateway
from core.message_bus import get_bus
from core.models import TradeSignal

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

logger = structlog.get_logger("oeg_service")


class OEGService:
    """OEG 微服务: 从消息总线消费信号, 执行下单, 推送结果"""
    
    def __init__(self):
        self.bus = get_bus()
        self.dry_run = CONFIG.flags.dry_run
        self.oeg = OrderExecutionGateway(
            result_callback=self._on_result,
            circuit_breaker_callback=self._on_circuit_breaker,
        )
        self._running = False
        self._poll_interval = 0.3 if not self.dry_run else 0.5
    
    async def _on_result(self, result) -> None:
        """OEG 执行结果推送到消息总线"""
        try:
            self.bus.push_result(
                signal_id=result.signal_id,
                condition_id=result.condition_id,
                yes_order_id=getattr(result.yes_result, 'order_id', '') or '',
                no_order_id=getattr(result.no_result, 'order_id', '') or '',
                yes_status=getattr(result.yes_result, 'status', 'UNKNOWN').value
                    if hasattr(getattr(result.yes_result, 'status', None), 'value')
                    else str(getattr(result.yes_result, 'status', 'UNKNOWN')),
                no_status=getattr(result.no_result, 'status', 'UNKNOWN').value
                    if hasattr(getattr(result.no_result, 'status', None), 'value')
                    else str(getattr(result.no_result, 'status', 'UNKNOWN')),
                yes_fill_price=getattr(result.yes_result, 'avg_fill_price', 0) or 0,
                no_fill_price=getattr(result.no_result, 'avg_fill_price', 0) or 0,
                yes_filled_size=getattr(result.yes_result, 'filled_size', 0) or 0,
                no_filled_size=getattr(result.no_result, 'filled_size', 0) or 0,
                realized_profit=result.realized_profit,
                has_leg_risk=getattr(result, 'has_leg_risk', False),
            )
            logger.info(
                "result_pushed",
                signal_id=result.signal_id[:8],
                profit=f"${result.realized_profit:.4f}",
            )
        except Exception as e:
            logger.error("push_result_error", error=str(e))
    
    def _on_circuit_breaker(self, condition_id: str) -> None:
        logger.warning("circuit_breaker_triggered", condition_id=condition_id[:16])
        self.oeg.disable_market(condition_id)
    
    async def start(self) -> None:
        mode = "影子系统 (DRY RUN)" if self.dry_run else "实盘"
        logger.info(f"OEG 微服务启动 - 模式: {mode}")
        self._running = True
        pid = os.getpid()
        
        if not self.bus.acquire_lock("oeg", pid):
            logger.error("OEG 服务锁已被占用, 退出")
            return
        
        try:
            if self.dry_run:
                await self._dry_run_loop(pid)
            else:
                await self._execution_loop(pid)
        except asyncio.CancelledError:
            logger.info("OEG 服务被取消")
        finally:
            self.bus.release_lock("oeg", pid)
            logger.info("OEG 服务已关闭")
    
    async def _execution_loop(self, pid: int) -> None:
        """实盘模式: 从消息总线拉取信号并通过 OEG 执行"""
        signal_queue = asyncio.Queue(maxsize=100)
        
        # 启动 OEG 内部执行循环
        oeg_task = asyncio.create_task(
            self.oeg.execution_loop(signal_queue),
            name="oeg_executor",
        )
        
        while self._running:
            try:
                signals = self.bus.poll_signals(limit=10, max_age=300.0)
                
                for sig_data in signals:
                    try:
                        signal = TradeSignal(
                            signal_id=sig_data["signal_id"],
                            condition_id=sig_data["condition_id"],
                            market_question=sig_data.get("market_question", ""),
                            yes_token_id=sig_data["yes_token_id"],
                            no_token_id=sig_data["no_token_id"],
                            yes_price=sig_data["yes_price"],
                            no_price=sig_data["no_price"],
                            yes_size=sig_data["yes_size"],
                            no_size=sig_data["no_size"],
                            expected_profit=sig_data["expected_profit"],
                            slippage_estimate=sig_data["slippage_estimate"],
                            total_cost=sig_data["total_cost"],
                            strategy=sig_data.get("strategy", "maker"),
                        )
                        await signal_queue.put(signal)
                        logger.info(
                            "signal_consumed",
                            signal_id=signal.signal_id[:8],
                            condition_id=signal.condition_id[:16],
                        )
                    except Exception as e:
                        logger.error("signal_deserialize_error", error=str(e))
                
                self.bus.heartbeat("oeg", pid)
                
                if not signals:
                    await asyncio.sleep(self._poll_interval)
                else:
                    await asyncio.sleep(0.05)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("oeg_poll_error", error=str(e))
                await asyncio.sleep(2.0)
        
        oeg_task.cancel()
        try:
            await oeg_task
        except asyncio.CancelledError:
            pass
    
    async def _dry_run_loop(self, pid: int) -> None:
        """影子模式: 只消费信号并记录"""
        logger.info("OEG 影子模式 (DRY RUN)")
        
        while self._running:
            try:
                signals = self.bus.poll_signals(limit=10, max_age=300.0)
                
                for sig_data in signals:
                    logger.info(
                        "DRY_RUN_SIGNAL",
                        signal_id=sig_data["signal_id"][:8],
                        condition_id=sig_data["condition_id"][:16],
                        question=sig_data.get("market_question", "")[:60],
                        profit=f"${sig_data['expected_profit']:.4f}",
                        strategy=sig_data.get("strategy", "maker"),
                    )
                    
                    self.bus.push_result(
                        signal_id=sig_data["signal_id"],
                        condition_id=sig_data["condition_id"],
                        yes_status="DRY_RUN",
                        no_status="DRY_RUN",
                        realized_profit=sig_data.get("expected_profit", 0),
                    )
                
                self.bus.heartbeat("oeg", pid)
                
                if not signals:
                    await asyncio.sleep(self._poll_interval)
                else:
                    await asyncio.sleep(0.1)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("dry_run_error", error=str(e))
                await asyncio.sleep(2.0)
    
    async def stop(self) -> None:
        self._running = False


def main():
    service = OEGService()
    asyncio.run(service.start())


if __name__ == "__main__":
    main()
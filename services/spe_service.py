"""
Polymarket 微服务入口: SPE (策略引擎)

独立进程运行, 从消息总线消费订单簿快照, 生成交易信号。
重启此服务不影响 MDG/OEG/RMC。

systemd: polymarket-spe.service
"""

import asyncio
import os
import sys
import time
import signal as sig
import structlog
import logging
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
from core.spe import StrategyPricingEngine
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

logger = structlog.get_logger("spe_service")

# SPE 信号处理回调: 推送到消息总线
_signal_id_dedup = set()


class SPEService:
    """SPE 微服务: 从消息总线消费快照, 生成交易信号"""
    
    def __init__(self):
        self.bus = get_bus()
        self.spe = StrategyPricingEngine(signal_callback=self._on_signal)
        self._running = False
        self._poll_interval = 0.5  # 秒, 消息总线轮询间隔
    
    def _on_signal(self, signal: TradeSignal) -> None:
        """SPE 生成交易信号时推送到消息总线"""
        global _signal_id_dedup
        
        # 去重: 60秒内同一信号不重复推送
        dedup_key = signal.signal_id
        if dedup_key in _signal_id_dedup:
            return
        _signal_id_dedup.add(dedup_key)
        
        # 清理过期去重键 (保留最近1000个)
        if len(_signal_id_dedup) > 1000:
            _signal_id_dedup = set(list(_signal_id_dedup)[-500:])
        
        try:
            self.bus.push_signal(
                signal_id=signal.signal_id,
                condition_id=signal.condition_id,
                market_question=getattr(signal, 'market_question', '')[:200],
                strategy=getattr(signal, 'strategy', 'maker'),
                yes_token_id=signal.yes_token_id,
                no_token_id=signal.no_token_id,
                yes_price=signal.yes_price,
                no_price=signal.no_price,
                yes_size=signal.yes_size,
                no_size=signal.no_size,
                expected_profit=signal.expected_profit,
                slippage_estimate=signal.slippage_estimate,
                total_cost=signal.total_cost,
            )
            logger.info(
                "signal_pushed",
                signal_id=signal.signal_id[:8],
                condition_id=signal.condition_id[:16],
                profit=f"${signal.expected_profit:.4f}",
            )
        except Exception as e:
            logger.error("push_signal_error", error=str(e))
    
    async def start(self) -> None:
        logger.info("SPE 微服务启动")
        self._running = True
        pid = os.getpid()
        
        if not self.bus.acquire_lock("spe", pid):
            logger.error("SPE 服务锁已被占用, 退出")
            return
        
        # 初始化市场发现 (SPE 需要知道有哪些市场)
        from core.mdg import MarketDataGateway
        mdg = MarketDataGateway(snapshot_callback=lambda s: None)
        markets = await mdg.discover_markets()
        for market in markets:
            self.spe.register_market(market)
        await mdg.stop()
        
        logger.info(f"SPE 已注册 {len(markets)} 个市场")
        
        # 主循环: 轮询消息总线
        try:
            await self._poll_loop(pid)
        except asyncio.CancelledError:
            logger.info("SPE 服务被取消")
        finally:
            self.bus.release_lock("spe", pid)
            logger.info("SPE 服务已关闭")
    
    async def _poll_loop(self, pid: int) -> None:
        """从消息总线轮询快照, 喂入 SPE 处理"""
        from core.models import OrderBookSnapshot, PriceLevel
        
        while self._running:
            try:
                # 从消息总线拉取未处理的快照
                snapshots = self.bus.poll_snapshots(limit=100, max_age=30.0)
                
                for snap in snapshots:
                    try:
                        # 重建 OrderBookSnapshot 对象
                        asks = [PriceLevel(price=float(a["price"]), size=float(a["size"]))
                                for a in snap["asks"][:50]]
                        bids = [PriceLevel(price=float(b["price"]), size=float(b["size"]))
                                for b in snap["bids"][:50]]
                        
                        snapshot = OrderBookSnapshot(
                            token_id=snap["token_id"],
                            condition_id=snap.get("condition_id", ""),
                            asks=asks,
                            bids=bids,
                            timestamp=snap["timestamp"],
                        )
                        
                        # 喂入 SPE
                        await self.spe.process_snapshot(snapshot)
                        
                    except Exception as e:
                        logger.error("process_snapshot_error",
                                     token_id=snap.get("token_id", "")[:16],
                                     error=str(e))
                
                # 心跳续期
                self.bus.heartbeat("spe", pid)
                
                # 没有快照时降低轮询频率
                if not snapshots:
                    await asyncio.sleep(self._poll_interval)
                # 有快照时立即处理下一批
                else:
                    await asyncio.sleep(0.05)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("spe_poll_error", error=str(e))
                await asyncio.sleep(2.0)


def main():
    service = SPEService()
    loop = asyncio.get_running_loop()
    for s in (sig.SIGINT, sig.SIGTERM):
        loop.add_signal_handler(s, lambda: asyncio.create_task(service.stop()))
    
    asyncio.run(service.start())


if __name__ == "__main__":
    main()
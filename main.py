"""
Polymarket 自动套利与对冲交易系统 - 主入口

架构概览:
┌─────────┐   Snapshot   ┌─────────┐   TradeSignal   ┌─────────┐
│   MDG   │ ───────────→ │   SPE   │ ───────────────→ │   OEG   │
│  市场数据 │              │  策略引擎 │                  │  订单执行 │
└─────────┘              └─────────┘                  └─────────┘
                                                              │
                               ArbitrageResult                │
                                                              ▼
                                                       ┌─────────┐
                                                       │   RMC   │
                                                       │  风控中心 │
                                                       └─────────┘

数据流转:
MDG → (asyncio.Queue) → SPE → (asyncio.Queue) → OEG → (callback) → RMC

启动模式:
  python main.py              → 真实执行模式 (Phase 3+)
  python main.py --dry-run     → 影子系统模式 (Phase 2)
  python main.py --discover    → 仅市场发现 (Phase 1)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import time
import sys
from pathlib import Path

# ============================================================
# 代理配置: 支持 mihomo/Clash 本地代理
# 自动从 ~/.proxyrc 加载, 也可通过 .env 的 PROXY_URL 指定
# ============================================================
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

import structlog

from core.config import CONFIG, validate_config
from core.mdg import MarketDataGateway
from core.oeg import OrderExecutionGateway
from core.rmc import RiskManagementCenter
from core.spe import StrategyPricingEngine
from core.heartbeat import telegram_heartbeat_loop
from core.phase3_notify import phase3_notify_loop

logger = structlog.get_logger(__name__)


def setup_logging(debug: bool = False) -> None:
    """配置 structlog 日志"""
    log_level = logging.DEBUG if debug else logging.INFO

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(message)s")


class ArbitrageEngine:
    """
    套利引擎 - 系统总调度
    
    职责:
    1. 初始化所有模块并建立数据通道
    2. 管理异步任务的生命周期
    3. 协调 MDG ↔ SPE ↔ OEG ↔ RMC 的数据流转
    4. 优雅关闭 (Graceful Shutdown)
    """

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

        # ── 异步队列 (模块间数据通道) ──
        self.snapshot_queue: asyncio.Queue = asyncio.Queue(maxsize=CONFIG.max_queue_size)
        self.signal_queue: asyncio.Queue = asyncio.Queue(maxsize=CONFIG.max_queue_size)

        # ── 初始化四大核心模块 ──
        # RMC 先初始化 (OEG 需要传给它回调)
        self.rmc = RiskManagementCenter()

        # OEG 需要结果回调和熔断回调
        self.oeg = OrderExecutionGateway(
            result_callback=self._on_arbitrage_result,
            circuit_breaker_callback=self._on_circuit_breaker,
            fill_update_callback=self.rmc.on_fill_update,
        )

        # 建立双向引用 (RMC 需要 OEG 引用来 disable_market)
        self.rmc.oeg = self.oeg

        # SPE 消费 snapshot_queue, 生产到 signal_queue
        self.spe = StrategyPricingEngine(signal_queue=self.signal_queue)

        # MDG 推送 snapshot 到 snapshot_queue
        self.mdg = MarketDataGateway(
            snapshot_callback=self._on_orderbook_snapshot
        )

        # ── 异步任务列表 ──
        self._tasks: list[asyncio.Task] = []
        self._running = False

    def _on_orderbook_snapshot(self, snapshot) -> None:
        """MDG 回调: 收到订单簿快照, 推入 SPE 输入队列"""
        try:
            self.snapshot_queue.put_nowait(snapshot)
        except asyncio.QueueFull:
            logger.warning("snapshot_queue_full, dropping update")

    async def _on_arbitrage_result(self, result) -> None:
        """OEG 回调: 收到套利执行结果, 交给 RMC 处理"""
        if self.dry_run:
            # 影子系统模式: 不执行真实下单, 只记录信号
            logger.info(
                "dry_run_arbitrage_result",
                signal_id=result.signal_id[:8],
                profit=f"${result.realized_profit:.4f}",
            )
        await self.rmc.on_arbitrage_result(result)

    def _on_circuit_breaker(self, condition_id: str) -> None:
        """OEG 触发熔断: 禁用特定市场"""
        self.oeg.disable_market(condition_id)


    async def _get_db_for_phase3(self):
        return self.rmc._db

    async def _collect_heartbeat_stats(self) -> dict:
        stats: dict = {
            "markets_monitored": len(getattr(self.spe, "_markets", {}) or {}),
            "oeg": self.oeg.get_stats(),
            "rmc": self.rmc.get_process_stats() if hasattr(self.rmc, "get_process_stats") else {},
        }
        rmc = stats.get("rmc") or {}
        if isinstance(rmc, dict) and rmc.get("last_signal_time"):
            stats["last_signal_time"] = rmc["last_signal_time"]
        if self.rmc._db:
            from datetime import datetime, timezone

            day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            try:
                cursor = await self.rmc._db.execute(
                    "SELECT COUNT(*) FROM trade_log WHERE timestamp >= ?",
                    (day_start,),
                )
                row = await cursor.fetchone()
                if row:
                    stats["trades_today"] = row[0]
            except Exception:
                stats["trades_today"] = "unavailable"
        try:
            from core.clob_client import get_collateral_balance_usd

            client = self.oeg._client or self.oeg._get_client()
            balance = await asyncio.to_thread(get_collateral_balance_usd, client)
            stats["clob_balance"] = f"${balance:.2f}" if balance is not None else "unavailable"
        except Exception:
            stats.setdefault("clob_balance", "unavailable")
        return stats

    async def start(self) -> None:
        """启动整个系统"""
        logger.info("=" * 60)
        logger.info("Polymarket 套利引擎启动")
        logger.info(f"模式: {'影子系统 (DRY RUN)' if self.dry_run else '实盘'}")
        logger.info(f"单笔上限: ${CONFIG.trading.max_trade_size}")
        logger.info(f"最小利润阈值: ${CONFIG.trading.min_profit_threshold}")
        logger.info("=" * 60)

        self._running = True
        self._started_at = time.time()

        # ── 初始化数据库 ──
        await self.rmc.init_db()

        # ── 发现市场 ──
        logger.info("[INIT] 正在通过 Gamma API 发现市场...")
        markets = await self.mdg.discover_markets()

        if not markets:
            logger.error("未发现任何活跃市场, 请检查 Gamma API 连通性")
            return

        logger.info(f"[INIT] 发现 {len(markets)} 个活跃市场")

        # 注册市场到 SPE
        for market in markets:
            self.spe.register_market(market)

        # ── 启动后台任务 ──
        self._tasks = [
            # MDG: 定期刷新市场列表
            asyncio.create_task(
                self.mdg.start_market_discovery_loop(),
                name="mdg_market_discovery",
            ),
            # SPE: 消费订单簿快照
            asyncio.create_task(
                self.spe.process_updates_loop(self.snapshot_queue),
                name="spe_orderbook_processor",
            ),
            # OEG: 消费交易信号 (仅实盘模式)
            asyncio.create_task(
                self.oeg.execution_loop(self.signal_queue)
                if not self.dry_run
                else self._dry_run_loop(),
                name="oeg_executor",
            ),
            # RMC: 定期维护
            asyncio.create_task(
                self.rmc.maintenance_loop(),
                name="rmc_maintenance",
            ),
            asyncio.create_task(
                telegram_heartbeat_loop(
                    self._collect_heartbeat_stats,
                    started_at=self._started_at,
                ),
                name="telegram_heartbeat",
            ),
            asyncio.create_task(
                phase3_notify_loop(
                    lambda: self._get_db_for_phase3(),
                    started_at=self._started_at,
                ),
                name="phase3_pass_notify",
            ),
        ]

        logger.info(f"[INIT] 已启动 {len(self._tasks)} 个后台任务")

        # ── 等待所有任务 ──
        try:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        except asyncio.CancelledError:
            logger.info("任务被取消, 正在关闭...")

    async def _dry_run_loop(self) -> None:
        """影子系统模式: 只消费信号并记录, 不执行真实下单"""
        logger.info("影子系统模式已启用 (DRY RUN)")

        while self._running:
            try:
                signal = await asyncio.wait_for(
                    self.signal_queue.get(), timeout=1.0
                )
                # 保存信号元数据到 RMC (用于日志补全)
                await self.rmc.on_trade_signal(signal)

                logger.info(
                    "DRY_RUN_SIGNAL",
                    signal_id=signal.signal_id[:8],
                    condition_id=signal.condition_id[:16],
                    question=signal.market_question[:60],
                    yes_price=f"{signal.yes_price:.4f}",
                    no_price=f"{signal.no_price:.4f}",
                    size=signal.yes_size,
                    expected_profit=f"${signal.expected_profit:.4f}",
                    slippage=f"${signal.slippage_estimate:.4f}",
                    total_cost=f"${signal.total_cost:.4f}",
                )

                # 模拟 300ms 网络延迟
                await asyncio.sleep(0.3)

                # 生成模拟成功结果
                from core.models import ArbitrageResult, ExecutionResult, OrderStatus, Side

                result = ArbitrageResult(
                    signal_id=signal.signal_id,
                    condition_id=signal.condition_id,
                    yes_result=ExecutionResult(
                        signal_id=signal.signal_id,
                        token_id=signal.yes_token_id,
                        side=Side.YES,
                        order_id=f"DRY-{signal.signal_id[:8]}-YES",
                        status=OrderStatus.MATCHED,
                        filled_size=signal.yes_size,
                        avg_fill_price=signal.yes_price,
                    ),
                    no_result=ExecutionResult(
                        signal_id=signal.signal_id,
                        token_id=signal.no_token_id,
                        side=Side.NO,
                        order_id=f"DRY-{signal.signal_id[:8]}-NO",
                        status=OrderStatus.MATCHED,
                        filled_size=signal.no_size,
                        avg_fill_price=signal.no_price,
                    ),
                    realized_profit=signal.expected_profit,
                    is_complete=True,
                )

                await self.rmc.on_arbitrage_result(result)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("dry_run_error", error=str(e))

    async def stop(self) -> None:
        """优雅关闭"""
        logger.info("正在优雅关闭套利引擎...")
        self._running = False

        # 取消所有后台任务
        for task in self._tasks:
            task.cancel()

        # 等待任务结束 (超时5秒)
        await asyncio.gather(*self._tasks, return_exceptions=True)

        # 关闭 MDG 的 WebSocket
        await self.mdg.stop()

        # 关闭数据库
        await self.rmc.close_db()

        # 统计输出
        stats = self.oeg.get_stats()
        logger.info(f"OEG 执行统计: {stats}")

        logger.info("套利引擎已关闭")


async def run_discover_only() -> None:
    """仅运行市场发现 (Phase 1 测试用)"""
    logger.info("市场发现模式启动...")

    mdg = MarketDataGateway(snapshot_callback=lambda s: None)
    markets = await mdg.discover_markets()

    if markets:
        logger.info(f"发现 {len(markets)} 个活跃市场:")
        for m in markets[:20]:  # 只显示前20个
            logger.info(
                f"  📊 {m.question[:60]}  "
                f" Vol=${m.volume:,.0f}  Liq=${m.liquidity:,.0f}"
            )
    else:
        logger.warning("未发现任何活跃市场")


async def run_engine(dry_run: bool) -> None:
    """运行主引擎"""
    engine = ArbitrageEngine(dry_run=dry_run)

    # 注册信号处理 (Ctrl+C 优雅关闭)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(engine.stop()))

    try:
        await engine.start()
    except KeyboardInterrupt:
        await engine.stop()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Polymarket 自动套利与对冲交易系统"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="影子系统模式: 不执行真实下单, 只记录信号 (Phase 2)",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="仅运行市场发现 (Phase 1 测试)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="启用 DEBUG 级别日志",
    )

    args = parser.parse_args()

    # 配置日志
    setup_logging(debug=args.debug)

    # 校验配置 (除 --discover 模式外)
    if not args.discover:
        errors = validate_config(CONFIG)
        for e in errors:
            logger.warning(f"⚠️  配置警告: {e}")
        critical_errors = [e for e in errors if "未配置" in e]
        if critical_errors and not args.dry_run:
            logger.error("❌ 关键配置缺失, 请检查 .env 文件")
            sys.exit(1)

    # 运行
    if args.discover:
        asyncio.run(run_discover_only())
    else:
        asyncio.run(run_engine(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
"""
Phase 2 测试脚本: 影子系统模式

运行方式:
  python test_phase2.py
  
预期行为:
  - 连接 Gamma API 发现市场
  - 建立 WebSocket 订阅实时订单簿
  - SPE 检测套利机会
  - 虚拟撮合 (Dry Run) - 不执行真实下单
  - 48小时信号积累与盈亏报表
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# 加载代理配置
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

from core.config import CONFIG
from core.mdg import MarketDataGateway
from core.oeg import OrderExecutionGateway
from core.rmc import RiskManagementCenter
from core.spe import StrategyPricingEngine

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="%H:%M:%S"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


class ShadowModeRunner:
    """
    影子系统运行器
    
    与主引擎的区别:
    1. 使用 Dry Run 模式 - 不执行真实下单
    2. 引入 300ms 模拟网络延迟
    3. 所有信号记录到 SQLite
    4. 定期输出理论盈亏报表
    """

    def __init__(self):
        self.snapshot_queue = asyncio.Queue(maxsize=CONFIG.max_queue_size)
        self.signal_queue = asyncio.Queue(maxsize=CONFIG.max_queue_size)

        # 初始化模块
        self.rmc = RiskManagementCenter()
        self.spe = StrategyPricingEngine(signal_queue=self.signal_queue)
        self.mdg = MarketDataGateway(
            snapshot_callback=self._on_snapshot
        )

        self._running = False
        self._signal_count = 0
        self._start_time = 0.0

    def _on_snapshot(self, snapshot):
        try:
            self.snapshot_queue.put_nowait(snapshot)
        except asyncio.QueueFull:
            pass

    async def start(self, duration_minutes: int = 5):
        """运行影子系统"""
        print("=" * 70)
        print("  🔬 Phase 2: 影子系统模式启动")
        print(f"  运行时长: {duration_minutes} 分钟")
        print(f"  模拟延迟: 300ms")
        print("=" * 70)
        print()

        self._running = True
        self._start_time = asyncio.get_event_loop().time()

        # 初始化数据库
        await self.rmc.init_db()

        # 发现市场
        print("📡 正在发现市场...")
        markets = await self.mdg.discover_markets()

        if not markets:
            print("❌ 未发现市场!")
            return

        print(f"✅ 发现 {len(markets)} 个市场")
        for m in markets[:5]:
            print(f"   - {m.question[:60]}")
            self.spe.register_market(m)

        print()

        # 启动后台任务
        tasks = [
            asyncio.create_task(
                self._dry_run_consumer(),
                name="dry_run_consumer",
            ),
            asyncio.create_task(
                self.spe.process_updates_loop(self.snapshot_queue),
                name="spe_processor",
            ),
            asyncio.create_task(
                self.rmc.maintenance_loop(),
                name="rmc_maintenance",
            ),
        ]

        # 运行指定时长
        elapsed_target = duration_minutes * 60
        try:
            await asyncio.sleep(elapsed_target)
        except KeyboardInterrupt:
            print("\n⚠️  收到中断信号...")

        self._running = False

        # 取消任务
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        await self.mdg.stop()

        # 生成报表
        print()
        print("=" * 70)
        print("  📊 影子系统运行报告")
        print("=" * 70)

        report = await self.rmc.generate_profit_report(hours=duration_minutes / 60)
        if report:
            print(f"  总交易次数: {report.get('total_trades', 0)}")
            print(f"  盈利次数: {report.get('winning_trades', 0)}")
            print(f"  总利润: ${report.get('total_profit', 0):.4f}")
            print(f"  平均滑点: {report.get('avg_slippage', 0):.4f}")
            print(f"  单边敞口次数: {report.get('leg_risk_count', 0)}")

        await self.rmc.close_db()

    async def _dry_run_consumer(self):
        """消费信号队列 - 影子系统核心"""
        while self._running:
            try:
                signal = await asyncio.wait_for(
                    self.signal_queue.get(),
                    timeout=1.0,
                )

                self._signal_count += 1
                elapsed = asyncio.get_event_loop().time() - self._start_time

                # 模拟网络延迟
                await asyncio.sleep(0.3)

                # 保存信号元数据到 RMC
                await self.rmc.on_trade_signal(signal)

                # 生成模拟结果
                from core.models import (
                    ArbitrageResult,
                    ExecutionResult,
                    OrderStatus,
                    Side,
                )

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

                # 理论利润累计
                spread = 1.0 - (signal.yes_price + signal.no_price)
                print(
                    f"  💰 信号 #{self._signal_count:04d} | "
                    f"市场: {signal.market_question[:40]} | "
                    f"YES={signal.yes_price:.4f} NO={signal.no_price:.4f} | "
                    f"价差={spread:.4f} | "
                    f"利润=${signal.expected_profit:.4f} | "
                    f"耗时={elapsed:.0f}s"
                )

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("dry_run_consumer_error", error=str(e))


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Phase 2 影子系统测试")
    parser.add_argument(
        "--duration",
        type=int,
        default=5,
        help="运行时长 (分钟), 默认5分钟",
    )
    args = parser.parse_args()

    runner = ShadowModeRunner()

    try:
        await runner.start(duration_minutes=args.duration)
    except KeyboardInterrupt:
        print("\n🛑 影子系统已停止")
        await runner.mdg.stop()
        await runner.rmc.close_db()


if __name__ == "__main__":
    asyncio.run(main())
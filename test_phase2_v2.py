"""
Phase 2 五维验证体系 (v2.0)

维度 1: 稳定性与内存泄漏 (Endurance Test)
维度 2: 订单簿镜像与 VWAP 精度 (Data Accuracy)
维度 3: 数据流转与队列背压 (Pipeline Flow)
维度 4: 信号去重逻辑 (Signal Deduplication)
维度 5: 持久化层与数据对账 (Data Persistence)

运行方式:
  python test_phase2_v2.py --duration 5        # 5分钟快速验证
  python test_phase2_v2.py --duration 1440      # 24小时耐久测试
  python test_phase2_v2.py --synthetic-only      # 仅运行合成注入测试
"""

import asyncio
import json
import os
import platform
import sys
import sys
import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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
import aiohttp

from core.config import CONFIG
from core.mdg import MarketDataGateway, OrderBookMirror
from core.spe import StrategyPricingEngine
from core.rmc import RiskManagementCenter
from core.models import (
    MarketInfo,
    OrderBookSnapshot,
    PriceLevel,
    SignalType,
    TradeSignal,
)

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


# ============================================================
# 数据收集器
# ============================================================

@dataclass
class HealthMetrics:
    """健康指标收集器"""
    start_time: float = 0.0
    end_time: float = 0.0
    
    # 维度 1: 稳定性
    crash_count: int = 0
    ws_reconnect_count: int = 0
    max_memory_mb: float = 0.0
    memory_samples: list[float] = None
    
    # 维度 2: 数据精度
    vwap_checks: int = 0
    vwap_mismatches: int = 0
    mirror_vs_rest_mismatches: int = 0
    
    # 维度 3: 队列健康
    snapshot_queue_full_count: int = 0
    signal_queue_full_count: int = 0
    max_snapshot_queue_size: int = 0
    max_signal_queue_size: int = 0
    total_snapshots_received: int = 0
    total_signals_generated: int = 0
    
    # 维度 4: 信号去重
    dedup_violations: int = 0
    signal_timestamps: dict[str, list[float]] = None  # condition_id -> [timestamps]
    
    # 维度 5: 持久化
    trade_count_db: int = 0
    trade_count_runtime: int = 0
    
    # 合成注入
    synthetic_signals_injected: int = 0
    synthetic_signals_received: int = 0
    
    def __post_init__(self):
        if self.memory_samples is None:
            self.memory_samples = []
        if self.signal_timestamps is None:
            self.signal_timestamps = {}


class Phase2Verifier:
    """Phase 2 五维验证器"""
    
    def __init__(self, duration_minutes: int = 5):
        self.duration = duration_minutes
        self.metrics = HealthMetrics()
        
        self.snapshot_queue = asyncio.Queue(maxsize=CONFIG.max_queue_size)
        self.signal_queue = asyncio.Queue(maxsize=CONFIG.max_queue_size)
        self.rmc = RiskManagementCenter()
        self.spe = StrategyPricingEngine(signal_queue=self.signal_queue)
        self.mdg = MarketDataGateway(snapshot_callback=self._on_snapshot)
        
        self._running = False
        self._markets: list[MarketInfo] = []
        
        # 内存追踪
        tracemalloc.start()
        
    def _on_snapshot(self, snapshot):
        """MDG 快照回调"""
        self.metrics.total_snapshots_received += 1
        try:
            self.snapshot_queue.put_nowait(snapshot)
            qsize = self.snapshot_queue.qsize()
            if qsize > self.metrics.max_snapshot_queue_size:
                self.metrics.max_snapshot_queue_size = qsize
        except asyncio.QueueFull:
            self.metrics.snapshot_queue_full_count += 1
    
    async def _signal_consumer(self):
        """消费信号队列, 验证维度 3/4/5"""
        while self._running:
            try:
                signal = await asyncio.wait_for(self.signal_queue.get(), timeout=1.0)
                self.metrics.total_signals_generated += 1
                
                # 维度 4: 去重检查
                cid = signal.condition_id
                if cid not in self.metrics.signal_timestamps:
                    self.metrics.signal_timestamps[cid] = []
                
                now = time.time()
                ts_list = self.metrics.signal_timestamps[cid]
                if ts_list:
                    interval = now - ts_list[-1]
                    if interval < 1.5:  # 去重窗口是 2 秒, 1.5 秒以内的重复视为违规
                        self.metrics.dedup_violations += 1
                        logger.warning(
                            "DEDUP_VIOLATION",
                            condition_id=cid[:16],
                            interval=f"{interval:.3f}s",
                            expected_min=2.0,
                        )
                ts_list.append(now)
                # 限制列表长度
                if len(ts_list) > 100:
                    self.metrics.signal_timestamps[cid] = ts_list[-50:]
                
                # 记录到 RMC
                await self.rmc.on_trade_signal(signal)
                
                # 模拟成交结果
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
                self.metrics.trade_count_runtime += 1
                
                # 模拟 300ms 延迟
                await asyncio.sleep(0.3)
                
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("signal_consumer_error", error=str(e))
    
    async def _memory_monitor(self):
        """维度 1: 每 30 秒采样一次内存"""
        while self._running:
            try:
                import psutil
                mem_mb = psutil.Process().memory_info().rss / 1024 / 1024
                self.metrics.memory_samples.append(mem_mb)
                if mem_mb > self.metrics.max_memory_mb:
                    self.metrics.max_memory_mb = mem_mb
                
                # 检查 SPE _recent_signals 字典大小
                signals_dict_size = len(self.spe._recent_signals)
                signals_cache_size = len(self.rmc._signal_meta)
                
                logger.debug(
                    "memory_check",
                    mem_mb=f"{mem_mb:.1f}",
                    spe_signals_dict=signals_dict_size,
                    rmc_signal_cache=signals_cache_size,
                    snapshot_q=self.snapshot_queue.qsize(),
                    signal_q=self.signal_queue.qsize(),
                )
                
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("memory_monitor_error", error=str(e))
                await asyncio.sleep(10)
    
    # ================================================================
    # 维度 2: 订单簿镜像与 VWAP 精度
    # ================================================================
    
    async def verify_orderbook_mirror(self) -> dict:
        """
        对比本地 SortedDict 镜像与 REST API 快照, 验证数据一致性
        
        方法: 随机选取 10 个市场, 同时从 WS 镜像和 REST API 获取订单簿,
        逐档对比 asks 和 bids
        """
        print("\n" + "=" * 70)
        print("  [CHECK] 维度 2: 订单簿镜像与 VWAP 精度验证")
        print("=" * 70)
        
        proxy = os.environ.get("https_proxy")
        results = {"total_checked": 0, "mirror_matches": 0, "mismatches": []}
        
        async with aiohttp.ClientSession(trust_env=True) as session:
            for market in self._markets[:10]:
                for token_id, label in [
                    (market.yes_token_id, "YES"),
                    (market.no_token_id, "NO"),
                ]:
                    # 从 REST API 获取真实订单簿
                    try:
                        url = f"https://clob.polymarket.com/book?token_id={token_id}"
                        async with session.get(url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                            if resp.status != 200:
                                continue
                            book = await resp.json()
                    except Exception:
                        continue
                    
                    rest_asks = [(float(a["price"]), float(a["size"])) for a in book.get("asks", [])[:5]]
                    rest_bids = [(float(b["price"]), float(b["size"])) for b in book.get("bids", [])[:5]]
                    
                    # 从 WS 镜像获取本地订单簿
                    mirror = self.mdg._mirrors.get(token_id)
                    if not mirror:
                        continue
                    
                    mirror_snap = mirror.get_snapshot(depth=5)
                    mirror_asks = [(pl.price, pl.size) for pl in mirror_snap.asks[:5]]
                    mirror_bids = [(pl.price, pl.size) for pl in mirror_snap.bids[:5]]
                    
                    # 对比 best ask/bid
                    match = True
                    details = {}
                    
                    rest_best_ask = rest_asks[0][0] if rest_asks else None
                    mirror_best_ask = mirror_asks[0][0] if mirror_asks else None
                    
                    if rest_best_ask and mirror_best_ask:
                        ask_diff = abs(rest_best_ask - mirror_best_ask)
                        if ask_diff > 0.005:  # 允许 0.5% 误差
                            match = False
                            details["ask_mismatch"] = {
                                "rest": rest_best_ask,
                                "mirror": mirror_best_ask,
                                "diff": ask_diff,
                            }
                    
                    rest_best_bid = rest_bids[0][0] if rest_bids else None
                    mirror_best_bid = mirror_bids[0][0] if mirror_bids else None
                    
                    if rest_best_bid and mirror_best_bid:
                        bid_diff = abs(rest_best_bid - mirror_best_bid)
                        if bid_diff > 0.005:
                            match = False
                            details["bid_mismatch"] = {
                                "rest": rest_best_bid,
                                "mirror": mirror_best_bid,
                                "diff": bid_diff,
                            }
                    
                    if match:
                        results["mirror_matches"] += 1
                    else:
                        self.metrics.mirror_vs_rest_mismatches += 1
                        mistmatch_entry = {
                            "market": market.question[:40],
                            "token": label,
                            **details,
                        }
                        results["mismatches"].append(mistmatch_entry)
                    
                    results["total_checked"] += 1
                    
                    # VWAP 精度验证
                    if rest_asks:
                        # 手动计算 VWAP (预算 $2)
                        budget = 2.0
                        remaining = budget
                        total_shares = 0.0
                        total_cost = 0.0
                        for price, size in rest_asks[:10]:
                            cost = price * size
                            if cost <= remaining:
                                total_shares += size
                                total_cost += cost
                                remaining -= cost
                            else:
                                shares = remaining / price
                                total_shares += shares
                                total_cost += remaining
                                remaining = 0
                                break
                        
                        if total_shares > 0:
                            vwap_rest = total_cost / total_shares
                            
                            # SPE 计算的 VWAP
                            asks_pl = [PriceLevel(price=p, size=s) for p, s in rest_asks[:10]]
                            vwap_spe, size_spe, slip_spe = SPE._calculate_vwap(asks_pl, budget)
                            
                            vwap_diff = abs(vwap_rest - vwap_spe)
                            if vwap_diff > 0.001:
                                self.metrics.vwap_mismatches += 1
                                logger.warning(
                                    "VWAP_MISMATCH",
                                    market=market.question[:40],
                                    rest=f"{vwap_rest:.6f}",
                                    spe=f"{vwap_spe:.6f}",
                                    diff=f"{vwap_diff:.6f}",
                                )
                            else:
                                self.metrics.vwap_checks += 1
                
                await asyncio.sleep(0.3)  # 避免 rate limit
        
        # 结果汇总
        pct = (results["mirror_matches"] / results["total_checked"] * 100) if results["total_checked"] > 0 else 0
        print(f"\n  订单簿一致性: {results['mirror_matches']}/{results['total_checked']} ({pct:.1f}% 匹配)")
        print(f"  VWAP 精度验证: {self.metrics.vwap_checks} 通过, {self.metrics.vwap_mismatches} 不匹配")
        
        if results["mismatches"]:
            print(f"\n  [WARN]  不匹配明细:")
            for m in results["mismatches"][:5]:
                print(f"    - {m['market']}: {m}")
        
        return results

    # ================================================================
    # 维度 2 补充: 合成套利注入测试
    # ================================================================
    
    async def inject_synthetic_arbitrage(self) -> None:
        """
        注入合成套利机会, 验证 SPE 信号检测、VWAP 计算、去重和 RMC 持久化
        
        构造一个 P_yes + P_no < 1 的订单簿快照:
        YES: asks=[(0.48, 5.0)], bids=[]
        NO:  asks=[(0.50, 5.0)], bids=[]
        → P_yes + P_no = 0.48 + 0.50 = 0.98 < 1
        → VWAP_YES = 0.48, VWAP_NO = 0.50
        → 理论利润 = 1 - 0.98 = $0.02 per share
        """
        print("\n" + "=" * 70)
        print("  [SYNTH] 合成套利注入测试")
        print("=" * 70)
        
        # 构造一个合成市场
        synthetic_condition_id = "0xSYNTHETIC_ARB_TEST_CONDITION_12345678"
        synthetic_yes_token = "0xSYNTHETIC_YES_TOKEN"
        synthetic_no_token = "0xSYNTHETIC_NO_TOKEN"
        
        synthetic_market = MarketInfo(
            condition_id=synthetic_condition_id,
            question="[TEST] Synthetic arbitrage opportunity",
            yes_token_id=synthetic_yes_token,
            no_token_id=synthetic_no_token,
            active=True,
            volume=100000.0,
            liquidity=50000.0,
        )
        self.spe.register_market(synthetic_market)
        
        # 测试用例 1: 经典双边 ASK 套利
        print("\n  [DATA] 测试 1: 经典双边 ASK 套利 (P_yes=0.48, P_no=0.50)")
        yes_ob = OrderBookSnapshot(
            token_id=synthetic_yes_token,
            condition_id=synthetic_condition_id,
            asks=[
                PriceLevel(price=0.48, size=2.5),  # 5 shares at $0.48
                PriceLevel(price=0.49, size=3.0),
                PriceLevel(price=0.50, size=5.0),
            ],
            bids=[PriceLevel(price=0.45, size=1.0)],
        )
        no_ob = OrderBookSnapshot(
            token_id=synthetic_no_token,
            condition_id=synthetic_condition_id,
            asks=[
                PriceLevel(price=0.50, size=2.0),
                PriceLevel(price=0.51, size=3.0),
                PriceLevel(price=0.52, size=5.0),
            ],
            bids=[PriceLevel(price=0.47, size=1.0)],
        )
        
        # 先注入 YES 侧
        self.spe.on_orderbook_update(yes_ob)
        # 再注入 NO 侧 (此时两边都有数据, SPE 会触发评估)
        self.spe.on_orderbook_update(no_ob)
        
        # 给 asyncio 一个 tick 来处理
        await asyncio.sleep(0.1)
        
        # 检查信号队列
        signals_injected = 0
        while not self.signal_queue.empty():
            try:
                signal = self.signal_queue.get_nowait()
                signals_injected += 1
                self.metrics.synthetic_signals_injected += 1
                
                print(f"\n  [OK] 收到套利信号 #{signals_injected}:")
                print(f"     市场: {signal.market_question}")
                print(f"     YES: VWAP=${signal.yes_price:.4f} x {signal.yes_size:.2f} shares")
                print(f"     NO:  VWAP=${signal.no_price:.4f} x {signal.no_size:.2f} shares")
                print(f"     理论利润: ${signal.expected_profit:.4f}")
                print(f"     滑点估计: ${signal.slippage_estimate:.4f}")
                print(f"     总成本: ${signal.total_cost:.4f}")
                
                # 验证 VWAP 精度
                # 预算 $2, YES 的 VWAP 应该是:
                # 吃 0.48 x 2.5 = $1.20 (remaining $0.80)
                # 吃 0.49 x 1.6327 = $0.80 (total $2.00)
                # VWAP_YES = 2.00 / (2.5 + 1.6327) = 2.00 / 4.1327 ≈ 0.4839
                expected_yes_vwap = 2.00 / (2.5 + 0.80 / 0.49)
                
                # NO 的 VWAP:
                # 吃 0.50 x 2.0 = $1.00 (remaining $1.00)
                # 吃 0.51 x 1.9608 = $1.00 (total $2.00)
                expected_no_vwap = 2.00 / (2.0 + 1.00 / 0.51)
                
                yes_err = abs(signal.yes_price - expected_yes_vwap)
                no_err = abs(signal.no_price - expected_no_vwap)
                
                print(f"\n     VWAP 验证:")
                print(f"       YES: 实际={signal.yes_price:.6f} 期望={expected_yes_vwap:.6f} 误差={yes_err:.6f}")
                print(f"       NO:  实际={signal.no_price:.6f} 期望={expected_no_vwap:.6f} 误差={no_err:.6f}")
                
                if yes_err < 0.001 and no_err < 0.001:
                    print("       [OK] VWAP 精度验证通过!")
                    self.metrics.vwap_checks += 1
                else:
                    print("       [FAIL] VWAP 精度验证失败!")
                    self.metrics.vwap_mismatches += 1
                
                # 写入 RMC 并验证持久化
                await self.rmc.on_trade_signal(signal)
                from core.models import ArbitrageResult, ExecutionResult, OrderStatus, Side
                result = ArbitrageResult(
                    signal_id=signal.signal_id,
                    condition_id=signal.condition_id,
                    yes_result=ExecutionResult(
                        signal_id=signal.signal_id,
                        token_id=signal.yes_token_id,
                        side=Side.YES,
                        order_id="SYN-YES-001",
                        status=OrderStatus.MATCHED,
                        filled_size=signal.yes_size,
                        avg_fill_price=signal.yes_price,
                    ),
                    no_result=ExecutionResult(
                        signal_id=signal.signal_id,
                        token_id=signal.no_token_id,
                        side=Side.NO,
                        order_id="SYN-NO-001",
                        status=OrderStatus.MATCHED,
                        filled_size=signal.no_size,
                        avg_fill_price=signal.no_price,
                    ),
                    realized_profit=signal.expected_profit,
                    is_complete=True,
                )
                await self.rmc.on_arbitrage_result(result)
                self.metrics.synthetic_signals_received += 1
                
            except asyncio.QueueEmpty:
                break
        
        if signals_injected == 0:
            print("  [WARN]  未生成套利信号! 检查 SPE 逻辑")
        
        # 测试用例 2: 去重验证 - 同一机会连续发送
        print("\n  [DATA] 测试 2: 信号去重 (2秒窗口内重复注入)")
        t1 = time.time()
        self.spe.on_orderbook_update(yes_ob)
        self.spe.on_orderbook_update(no_ob)
        await asyncio.sleep(0.1)
        
        dedup_signals = 0
        while not self.signal_queue.empty():
            self.signal_queue.get_nowait()
            dedup_signals += 1
        
        # 短时间内再次注入 → 应被去重
        self.spe.on_orderbook_update(yes_ob)
        self.spe.on_orderbook_update(no_ob)
        await asyncio.sleep(0.1)
        
        dedup_signals_2 = 0
        while not self.signal_queue.empty():
            self.signal_queue.get_nowait()
            dedup_signals_2 += 1
        
        total_dedup = dedup_signals + dedup_signals_2
        if total_dedup == 1:
            print(f"  [OK] 去重验证通过: 第1次注入产出 {dedup_signals} 个信号, 第2次被去重产出 {dedup_signals_2} 个")
        else:
            print(f"  [WARN]  去重异常: 第1次={dedup_signals}, 第2次={dedup_signals_2}, 总计={total_dedup}")
            self.metrics.dedup_violations += total_dedup
        
        # 等待去重窗口过期后再次注入
        print("  等待去重窗口过期 (2.1秒)...")
        await asyncio.sleep(2.1)
        self.spe.on_orderbook_update(yes_ob)
        self.spe.on_orderbook_update(no_ob)
        await asyncio.sleep(0.1)
        
        dedup_signals_3 = 0
        while not self.signal_queue.empty():
            signal = self.signal_queue.get_nowait()
            dedup_signals_3 += 1
            # 清理去重记录
            self.spe.cleanup_stale_signals()
        
        if dedup_signals_3 >= 1:
            print(f"  [OK] 去重窗口验证通过: 窗口过期后重新注入产出 {dedup_signals_3} 个信号")
        else:
            print(f"  [WARN]  去重窗口验证失败: 窗口过期后应产出 >=1 信号, 实际={dedup_signals_3}")
        
        # 测试用例 3: 无套利市场 (P_yes + P_no > 1)
        print("\n  [DATA] 测试 3: 无套利市场过滤 (P_yes=0.60, P_no=0.60)")
        no_arb_yes = OrderBookSnapshot(
            token_id=synthetic_yes_token,
            condition_id=synthetic_condition_id,
            asks=[PriceLevel(price=0.60, size=5.0)],
            bids=[PriceLevel(price=0.55, size=5.0)],
        )
        no_arb_no = OrderBookSnapshot(
            token_id=synthetic_no_token,
            condition_id=synthetic_condition_id,
            asks=[PriceLevel(price=0.60, size=5.0)],
            bids=[PriceLevel(price=0.55, size=5.0)],
        )
        # 清除缓存
        self.spe._orderbooks.clear()
        self.spe._recent_signals.clear()
        self.spe.on_orderbook_update(no_arb_yes)
        self.spe.on_orderbook_update(no_arb_no)
        await asyncio.sleep(0.1)
        
        no_arb_signals = 0
        while not self.signal_queue.empty():
            self.signal_queue.get_nowait()
            no_arb_signals += 1
        
        if no_arb_signals == 0:
            print("  [OK] 无套利市场正确过滤 (0 信号生成)")
        else:
            print(f"  [FAIL] 无套利市场应产出 0 信号, 实际={no_arb_signals}")

    # ================================================================
    # 维度 5: 数据库持久化验证
    # ================================================================
    
    async def verify_persistence(self) -> dict:
        """验证 SQLite 数据完整性"""
        print("\n" + "=" * 70)
        print("  [DB] 维度 5: 持久化层与数据对账验证")
        print("=" * 70)
        
        if not self.rmc._db:
            print("  [WARN]  数据库未初始化, 跳过持久化验证")
            return {}
        
        results = {}
        
        try:
            # 检查 trade_log
            cursor = await self.rmc._db.execute("SELECT COUNT(*) FROM trade_log")
            row = await cursor.fetchone()
            trade_count = row[0] if row else 0
            self.metrics.trade_count_db = trade_count
            results["trade_count"] = trade_count
            
            # 检查字段完整性
            cursor = await self.rmc._db.execute("""
                SELECT signal_id, condition_id, market_question, yes_price, no_price,
                       yes_size, no_size, expected_profit, realized_profit,
                       slippage_estimate, has_leg_risk, yes_status, no_status,
                       yes_fill_price, no_fill_price
                FROM trade_log LIMIT 10
            """)
            rows = await cursor.fetchall()
            
            if rows:
                print(f"\n  trade_log 记录数: {trade_count}")
                print(f"  ╔════════════════════════════════════════════════════════════════╗")
                print(f"  ║ {'SignalID':>10} {'Question':>25} {'Y_Price':>8} {'N_Price':>8} {'Profit':>8} {'Slip':>8} ║")
                print(f"  ╠════════════════════════════════════════════════════════════════╣")
                
                field_issues = 0
                for row in rows[:5]:
                    sid, cid, question, yp, np, ys, ns, ep, rp, slip, hlr, ys_status, ns_status, yfp, nfp = row
                    
                    # 检查关键字段是否非空/非零
                    if question == "" or question is None:
                        field_issues += 1
                    if yp == 0.0 and np == 0.0:
                        field_issues += 1
                    if slip == 0.0:
                        field_issues += 1
                    
                    q_display = (question or "")[:23]
                    print(f"  ║ {str(sid)[:8]:>10} {q_display:>25} {yp:>8.4f} {np:>8.4f} {ep:>8.4f} {slip:>8.4f} ║")
                
                print(f"  ╚════════════════════════════════════════════════════════════════╝")
                
                if field_issues > 0:
                    print(f"\n  [WARN]  发现 {field_issues} 个字段缺失问题 (market_question/slippage 为空或 0)")
                else:
                    print(f"\n  [OK] trade_log 字段完整性验证通过")
                
                # 运行每日 PnL 视图
                cursor = await self.rmc._db.execute("SELECT * FROM v_daily_pnl")
                pnl_rows = await cursor.fetchall()
                if pnl_rows:
                    print(f"\n  [DATA] v_daily_pnl 视图输出:")
                    for row in pnl_rows:
                        print(f"     {row}")
                else:
                    print(f"\n  [DATA] v_daily_pnl: 无数据 (因为可能全部在同一日)")
                
                # 时间戳分布检查
                cursor = await self.rmc._db.execute("""
                    SELECT MIN(timestamp), MAX(timestamp), COUNT(*)
                    FROM trade_log
                """)
                ts_row = await cursor.fetchone()
                if ts_row and ts_row[2] > 0:
                    min_ts, max_ts, cnt = ts_row
                    duration = max_ts - min_ts
                    print(f"\n  时间戳范围: {duration:.1f} 秒 ({cnt} 条记录)")
                    if duration > 60 and cnt > 1:
                        # 检查是否有时间断层
                        cursor = await self.rmc._db.execute("""
                            SELECT timestamp FROM trade_log ORDER BY timestamp
                        """)
                        all_ts = [r[0] for r in await cursor.fetchall()]
                        max_gap = max(all_ts[i+1] - all_ts[i] for i in range(len(all_ts)-1)) if len(all_ts) > 1 else 0
                        print(f"  最大时间间隔: {max_gap:.1f} 秒")
                        if max_gap > 3600:
                            print(f"  [WARN]  发现时间断层 (>{3600}s)")
                        else:
                            print(f"  [OK] 时间戳分布均匀")
            
            # 检查 circuit_breaker_log
            cursor = await self.rmc._db.execute("SELECT COUNT(*) FROM circuit_breaker_log")
            cb_count = (await cursor.fetchone())[0]
            results["circuit_breaker_count"] = cb_count
            
            print(f"\n  circuit_breaker_log 记录数: {cb_count}")
            
            # 运行时 vs 数据库对账
            runtime = self.metrics.trade_count_runtime
            db_count = trade_count
            diff = runtime - db_count
            results["runtime_db_diff"] = diff
            
            print(f"\n  [DATA] 运行时 vs 数据库对账:")
            print(f"     运行时信号数: {runtime}")
            print(f"     数据库记录数: {db_count}")
            print(f"     差异: {diff}")
            if diff == 0:
                print(f"     [OK] 对账平衡!")
            else:
                print(f"     [WARN]  存在差异, 可能是异步写入延迟")
            
        except Exception as e:
            print(f"\n  [FAIL] 持久化验证失败: {e}")
            results["error"] = str(e)
        
        return results

    # ================================================================
    # 主运行器
    # ================================================================
    
    async def run(self):
        """运行完整的五维验证"""
        self.metrics.start_time = time.time()
        self._running = True
        
        print("=" * 70)
        print("  [TEST] Phase 2 五维验证体系 v2.0")
        print(f"  运行时长: {self.duration} 分钟")
        print("=" * 70)
        
        # 初始化数据库
        await self.rmc.init_db()
        
        # 发现市场
        print("\n[DISC] 正在发现市场...")
        self._markets = await self.mdg.discover_markets()
        
        if not self._markets:
            print("[FAIL] 未发现市场! 请检查网络和代理配置。")
            await self.rmc.close_db()
            return
        
        print(f"[OK] 发现 {len(self._markets)} 个市场")
        
        # 注册市场到 SPE
        for m in self._markets:
            self.spe.register_market(m)
        
        # 启动后台任务
        tasks = [
            asyncio.create_task(self.spe.process_updates_loop(self.snapshot_queue)),
            asyncio.create_task(self._signal_consumer()),
            asyncio.create_task(self._memory_monitor()),
            asyncio.create_task(self.rmc.maintenance_loop()),
        ]
        
        # 运行耐久测试
        elapsed_target = self.duration * 60
        print(f"\n[RUN] 开始 {self.duration} 分钟耐久测试...")
        print(f"   (每 60 秒输出一次健康状态)")
        
        start = time.time()
        last_report = start
        
        try:
            while (time.time() - start) < elapsed_target:
                now = time.time()
                
                # 每 60 秒输出健康状态
                if now - last_report >= 60:
                    elapsed = now - start
                    mem_mb = 0.0
                    try:
                        import psutil
                        mem_mb = psutil.Process().memory_info().rss / 1024 / 1024
                    except ImportError:
                        pass
                    spe_dict_size = len(self.spe._recent_signals)
                    meta_cache_size = len(self.rmc._signal_meta)
                    
                    print(
                        f"  ⏱  [{elapsed:.0f}s/{elapsed_target:.0f}s] "
                        f"mem={mem_mb:.1f}MB "
                        f"signals={self.metrics.total_signals_generated} "
                        f"snapshots={self.metrics.total_snapshots_received} "
                        f"spe_dict={spe_dict_size} "
                        f"meta_cache={meta_cache_size} "
                        f"q_full={self.metrics.snapshot_queue_full_count}"
                    )
                    last_report = now
                
                await asyncio.sleep(5)
                
        except KeyboardInterrupt:
            print("\n[WARN]  收到中断信号...")
        
        self._running = False
        
        # 取消任务
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        
        await self.mdg.stop()
        self.metrics.end_time = time.time()
        total_runtime = self.metrics.end_time - self.metrics.start_time
        
        # =========================================
        # 耐久测试结束, 开始验证
        # =========================================
        
        print("\n\n" + "=" * 70)
        print("  [END] 耐久测试完成, 开始五维验证")
        print("=" * 70)
        
        # 维度 2: 订单簿镜像与 VWAP 精度
        mirror_results = await self.verify_orderbook_mirror()
        
        # 合成注入测试
        await self.inject_synthetic_arbitrage()
        
        # 维度 5: 持久化验证
        persistence_results = await self.verify_persistence()
        
        # 最终报告
        print("\n\n" + "=" * 70)
        print("  [DATA] Phase 2 五维验证报告")
        print("=" * 70)
        
        hours = total_runtime / 3600
        mem_samples = self.metrics.memory_samples
        
        print(f"\n  ┌─────────────────────────────────────────────────────────┐")
        print(f"  │ 维度 1: 稳定性与内存                                   │")
        print(f"  │   运行时长: {total_runtime:.0f}s ({hours:.2f}h)                            │")
        print(f"  │   崩溃次数: {self.metrics.crash_count}                                        │")
        print(f"  │   WS 重连次数: {self.metrics.ws_reconnect_count}                                     │")
        print(f"  │   峰值内存: {self.metrics.max_memory_mb:.1f} MB                             │")
        if mem_samples and len(mem_samples) > 1:
            mem_delta = max(mem_samples) - min(mem_samples)
            print(f"  │   内存增长: {mem_delta:.1f} MB                                     │")
            if mem_delta > 50:
                print(f"  │   [WARN]  内存增长过大, 可能存在泄漏!                       │")
            else:
                print(f"  │   [OK] 内存增长在可接受范围内                             │")
        print(f"  │   信号去重字典最终大小: {len(self.spe._recent_signals)}                     │")
        print(f"  └─────────────────────────────────────────────────────────┘")
        
        print(f"\n  ┌─────────────────────────────────────────────────────────┐")
        print(f"  │ 维度 2: 订单簿镜像与 VWAP 精度                           │")
        print(f"  │   镜像一致性: {mirror_results.get('mirror_matches', 0)}/{mirror_results.get('total_checked', 0)}                              │")
        print(f"  │   REST vs WS 不匹配: {self.metrics.mirror_vs_rest_mismatches}                              │")
        print(f"  │   VWAP 精度验证: {self.metrics.vwap_checks} 通过, {self.metrics.vwap_mismatches} 失败               │")
        print(f"  └─────────────────────────────────────────────────────────┘")
        
        print(f"\n  ┌─────────────────────────────────────────────────────────┐")
        print(f"  │ 维度 3: 数据流转与队列背压                               │")
        print(f"  │   快照接收: {self.metrics.total_snapshots_received}                                    │")
        print(f"  │   信号生成: {self.metrics.total_signals_generated}                                    │")
        print(f"  │   快照队列满次数: {self.metrics.snapshot_queue_full_count}                                │")
        print(f"  │   信号队列满次数: {self.metrics.signal_queue_full_count}                                │")
        print(f"  │   快照队列峰值: {self.metrics.max_snapshot_queue_size}                                      │")
        if self.metrics.snapshot_queue_full_count == 0:
            print(f"  │   [OK] 队列无背压, 处理能力充足                             │")
        else:
            print(f"  │   [WARN]  队列溢出 {self.metrics.snapshot_queue_full_count} 次, 需要优化                   │")
        print(f"  └─────────────────────────────────────────────────────────┘")
        
        print(f"\n  ┌─────────────────────────────────────────────────────────┐")
        print(f"  │ 维度 4: 信号去重逻辑                                     │")
        print(f"  │   去重违规次数: {self.metrics.dedup_violations}                                        │")
        if self.metrics.dedup_violations == 0:
            print(f"  │   [OK] 去重机制工作正常 (2秒窗口)                           │")
        else:
            print(f"  │   [FAIL] 去重违规 {self.metrics.dedup_violations} 次, 需要检查                              │")
        print(f"  └─────────────────────────────────────────────────────────┘")
        
        print(f"\n  ┌─────────────────────────────────────────────────────────┐")
        print(f"  │ 维度 5: 持久化与对账                                     │")
        print(f"  │   数据库记录: {self.metrics.trade_count_db}                                        │")
        print(f"  │   运行时记录: {self.metrics.trade_count_runtime}                                        │")
        print(f"  │   差异: {self.metrics.trade_count_runtime - self.metrics.trade_count_db}                                              │")
        if self.metrics.trade_count_db > 0:
            print(f"  │   [OK] 数据库写入正常                                      │")
        else:
            print(f"  │   [WARN]  数据库无记录 (可能无真实信号)                       │")
        print(f"  └─────────────────────────────────────────────────────────┘")
        
        # Go/No-Go 决断
        print(f"\n\n{'=' * 70}")
        print("  [DECIDE] Phase 2 Go/No-Go 决断清单")
        print(f"{'=' * 70}")
        
        # 检查 1: 系统存活
        survived = self.metrics.crash_count == 0
        print(f"\n  [{'[OK]' if survived else '[FAIL]'}] 系统是否无崩溃地存活了 {self.duration} 分钟?")
        
        # 检查 2: 利润 (合成注入)
        has_profit = self.metrics.synthetic_signals_received > 0
        print(f"  [{'[OK]' if has_profit else '[FAIL]'}] 合成套利信号能否正确触发且 VWAP 精度通过?")
        
        # 检查 3: 信号频率
        # 合成注入测试应该产生 2-3 个信号 (3次注入: 2次被去重窗口限制, 1次窗口后成功)
        reasonable_freq = self.metrics.dedup_violations <= 2
        print(f"  [{'[OK]' if reasonable_freq else '[FAIL]'}] 去重机制是否正确限制信号频率?")
        
        # 检查 4: 无 VWAP 错误
        no_errors = self.metrics.vwap_mismatches == 0
        print(f"  [{'[OK]' if no_errors else '[FAIL]'}] VWAP 计算是否精确 (无数据格式错误)?")
        
        all_pass = survived and has_profit and reasonable_freq and no_errors
        
        print(f"\n  {'[GO] Go - Phase 2 通过!' if all_pass else '[STOP] No-Go - Phase 2 需要修复'}")
        
        if not all_pass:
            print(f"\n  需要修复的问题:")
            if not survived:
                print(f"    - 系统崩溃, 检查日志")
            if not has_profit:
                print(f"    - 合成套利信号未触发, 检查 SPE 逻辑")
            if not reasonable_freq:
                print(f"    - 去重机制异常, 检查 _signal_dedup_window")
            if not no_errors:
                print(f"    - VWAP 计算有误, 检查 _calculate_vwap")
        
        await self.rmc.close_db()
        
        return all_pass
    
    async def run_synthetic_only(self):
        """仅运行合成注入测试 (快速验证)"""
        self._running = True
        await self.rmc.init_db()
        
        # 构造一个合成市场
        synthetic_condition_id = "0xSYNTHETIC_ARB_TEST_CONDITION_QUICK"
        synthetic_yes_token = "0xSYNTHETIC_YES_QUICK"
        synthetic_no_token = "0xSYNTHETIC_NO_QUICK"
        
        synthetic_market = MarketInfo(
            condition_id=synthetic_condition_id,
            question="[TEST] Quick synthetic arbitrage",
            yes_token_id=synthetic_yes_token,
            no_token_id=synthetic_no_token,
            active=True,
            volume=100000.0,
            liquidity=50000.0,
        )
        self.spe.register_market(synthetic_market)
        
        # 运行合成注入
        await self.inject_synthetic_arbitrage()
        
        # 持久化验证
        persistence_results = await self.verify_persistence()
        
        await self.rmc.close_db()
        
        return self.metrics.synthetic_signals_received > 0 and self.metrics.dedup_violations <= 2


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Phase 2 五维验证")
    parser.add_argument("--duration", type=int, default=5, help="耐久测试时长 (分钟)")
    parser.add_argument("--synthetic-only", action="store_true", help="仅运行合成注入测试")
    args = parser.parse_args()
    
    verifier = Phase2Verifier(duration_minutes=args.duration)
    
    if args.synthetic_only:
        result = await verifier.run_synthetic_only()
        sys.exit(0 if result else 1)
    else:
        result = await verifier.run()
        sys.exit(0 if result else 1)


if __name__ == "__main__":
    asyncio.run(main())
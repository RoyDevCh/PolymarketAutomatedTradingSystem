"""
Polymarket 自动套利系统 - 策略与定价引擎 (SPE)

职责:
1. 监听 MDG 推送的订单簿快照
2. 匹配同一市场的 YES/NO 双向 Ask
3. VWAP 计算: 穿透订单簿模拟真实滑点
4. 套利信号检测: P_yes + P_no + Slippage < 1
5. 生成 TradeSignal 推入执行队列
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from typing import Optional

import structlog

from core.config import CONFIG
from core.models import (
    MarketInfo,
    OrderBookSnapshot,
    PriceLevel,
    SignalType,
    TradeSignal,
)

logger = structlog.get_logger(__name__)


class StrategyPricingEngine:
    """
    策略与定价引擎 (SPE)
    
    核心套利逻辑:
    ┌────────────────────────────────────────────────────┐
    │  在同一二元预测市场中:                                │
    │                                                      │
    │  如果 Ask(YES) + Ask(NO) < 1                         │
    │  且 理论利润 - 预估滑点 > MIN_PROFIT_THRESHOLD       │
    │                                                      │
    │  → 同时买入 YES + NO                                  │
    │  → 无论结果如何, 赔付 1 USD, 成本 < 1 USD             │
    │  → 锁定无风险利润 = 1 - (P_yes + P_no)               │
    └────────────────────────────────────────────────────┘
    """

    def __init__(self, signal_queue: asyncio.Queue):
        self.cfg = CONFIG.trading

        # 执行队列: 满足条件的 TradeSignal 推入此处, OEG 消费
        self.signal_queue = signal_queue

        # 订单簿缓存: token_id -> OrderBookSnapshot
        self._orderbooks: dict[str, OrderBookSnapshot] = {}

        # 市场注册表: condition_id -> MarketInfo (由 MDG 提供)
        self._markets: dict[str, MarketInfo] = {}

        # condition_id -> YES/NO token_id 映射
        self._condition_to_tokens: dict[str, dict[str, str]] = {}

        # 去重: 最近 N 秒内已发出的信号, 防止重复下单
        self._recent_signals: dict[str, float] = {}
        self._signal_dedup_window: float = 2.0  # 2秒去重窗口

    def register_market(self, market: MarketInfo) -> None:
        """注册市场信息 (由 MDG 调用)"""
        self._markets[market.condition_id] = market
        self._condition_to_tokens[market.condition_id] = {
            "yes": market.yes_token_id,
            "no": market.no_token_id,
        }

    def on_orderbook_update(self, snapshot: OrderBookSnapshot) -> None:
        """
        MDG 回调: 收到订单簿快照时触发
        
        流程:
        1. 更新本地缓存
        2. 查找对应的另一侧 (YES↔NO) 订单簿
        3. 执行套利计算
        4. 满足条件则生成 TradeSignal
        """
        # 更新缓存
        self._orderbooks[snapshot.token_id] = snapshot

        # 查找 condition_id
        condition_id = snapshot.condition_id
        if not condition_id:
            # 尝试通过遍历查找
            condition_id = self._find_condition(snapshot.token_id)
            if not condition_id:
                return

        tokens = self._condition_to_tokens.get(condition_id)
        if not tokens:
            return

        # 判断当前是 YES 还是 NO
        is_yes = snapshot.token_id == tokens["yes"]
        other_token = tokens["no"] if is_yes else tokens["yes"]

        # 检查另一侧订单簿是否已缓存
        other_ob = self._orderbooks.get(other_token)
        if not other_ob or not other_ob.asks:
            return

        # 确定 YES 和 NO 的订单簿
        yes_ob = snapshot if is_yes else other_ob
        no_ob = other_ob if is_yes else snapshot

        # 执行套利计算
        self._evaluate_arbitrage(condition_id, yes_ob, no_ob)

    def _evaluate_arbitrage(
        self,
        condition_id: str,
        yes_ob: OrderBookSnapshot,
        no_ob: OrderBookSnapshot,
    ) -> None:
        """
        核心套利评估
        
        步骤:
        1. 检查双方 best ask 是否存在
        2. 计算理论价差: spread = 1 - (best_ask_yes + best_ask_no)
        3. 计算 VWAP: 穿透订单簿至 max_trade_size
        4. 检查利润阈值
        5. 生成 TradeSignal
        """
        if not yes_ob.asks or not no_ob.asks:
            return

        best_ask_yes = yes_ob.best_ask
        best_ask_no = no_ob.best_ask

        if not best_ask_yes or not best_ask_no:
            return

        # ================================================================
        # 步骤 1: 理论价差检查 (快速预筛选)
        # ================================================================
        theoretical_spread = 1.0 - (best_ask_yes.price + best_ask_no.price)
        if theoretical_spread <= 0:
            return  # 无套利空间

        # ================================================================
        # 步骤 2: VWAP 计算 - 穿透订单簿模拟真实成本
        # ================================================================
        trade_size_usd = self.cfg.max_trade_size

        vwap_yes, size_yes, slip_yes = self._calculate_vwap(
            yes_ob.asks, trade_size_usd
        )
        vwap_no, size_no, slip_no = self._calculate_vwap(
            no_ob.asks, trade_size_usd
        )

        # 取两者较小值为实际可成交量
        actual_size = min(size_yes, size_no)
        if actual_size <= 0:
            return

        # ================================================================
        # 步骤 3: 实际利润计算
        # ================================================================
        total_cost = vwap_yes * actual_size + vwap_no * actual_size
        total_payout = actual_size  # 二元市场: 无论 YES/NO, 赔付 $1 * size
        expected_profit = total_payout - total_cost
        total_slippage = (slip_yes + slip_no) * actual_size

        # 扣除滑点后的净利
        net_profit = expected_profit - total_slippage

        if net_profit < self.cfg.min_profit_threshold:
            return

        # ================================================================
        # 步骤 4: 去重检查
        # ================================================================
        signal_key = f"{condition_id}:{vwap_yes:.4f}:{vwap_no:.4f}"
        now = time.time()
        last_sent = self._recent_signals.get(signal_key, 0)
        if now - last_sent < self._signal_dedup_window:
            return  # 2秒内已发过类似信号, 跳过

        self._recent_signals[signal_key] = now

        # ================================================================
        # 步骤 5: 生成 TradeSignal
        # ================================================================
        market = self._markets.get(condition_id, None)
        question = market.question if market else condition_id[:16]

        signal = TradeSignal(
            signal_id=str(uuid.uuid4()),
            signal_type=SignalType.ARBITRAGE,
            condition_id=condition_id,
            market_question=question,
            yes_token_id=yes_ob.token_id,
            yes_price=vwap_yes,
            yes_size=actual_size,
            no_token_id=no_ob.token_id,
            no_price=vwap_no,
            no_size=actual_size,
            expected_profit=net_profit,
            slippage_estimate=total_slippage,
            total_cost=total_cost,
            timestamp=now,
            priority=0,  # 0=最高优先级
        )

        # 推入执行队列
        try:
            self.signal_queue.put_nowait(signal)
            logger.info(
                "arbitrage_signal_generated",
                signal_id=signal.signal_id[:8],
                question=question[:50],
                vwap_yes=f"{vwap_yes:.4f}",
                vwap_no=f"{vwap_no:.4f}",
                size=actual_size,
                profit=f"${net_profit:.4f}",
                spread=f"{theoretical_spread:.4f}",
            )
        except asyncio.QueueFull:
            logger.warning("signal_queue_full, dropping signal")

    @staticmethod
    def _calculate_vwap(
        asks: list[PriceLevel], max_budget_usd: float
    ) -> tuple[float, float, float]:
        """
        计算 VWAP (成交量加权平均价)
        
        模拟以 max_budget_usd 的资金穿透订单簿:
        - 从最优 ask 逐档吃入
        - 计算加权平均成交价
        - 计算滑点 = VWAP - best_ask_price
        
        Returns:
            (vwap, total_size_acquired, total_slippage_cost)
        """
        if not asks:
            return 0.0, 0.0, 0.0

        best_ask_price = asks[0].price
        remaining_budget = max_budget_usd
        total_cost = 0.0
        total_size = 0.0

        for level in asks:
            if remaining_budget <= 0:
                break

            # 该档可提供的份额
            level_cost = level.price * level.size

            if level_cost <= remaining_budget:
                # 完全吃入该档
                total_cost += level_cost
                total_size += level.size
                remaining_budget -= level_cost
            else:
                # 部分吃入
                partial_size = remaining_budget / level.price
                total_cost += remaining_budget
                total_size += partial_size
                remaining_budget = 0

        if total_size <= 0:
            return 0.0, 0.0, 0.0

        vwap = total_cost / total_size
        slippage = (vwap - best_ask_price) * total_size

        return vwap, total_size, slippage

    def _find_condition(self, token_id: str) -> Optional[str]:
        """通过 token_id 反查 condition_id"""
        for cid, tokens in self._condition_to_tokens.items():
            if token_id in tokens.values():
                return cid
        return None

    async def process_updates_loop(self, queue: asyncio.Queue) -> None:
        """后台任务: 从队列中持续消费订单簿更新"""
        while True:
            try:
                snapshot: OrderBookSnapshot = await asyncio.wait_for(
                    queue.get(), timeout=1.0
                )
                self.on_orderbook_update(snapshot)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("spe_process_error", error=str(e))
                await asyncio.sleep(0.1)

    def cleanup_stale_signals(self, max_age: float = 60.0) -> None:
        """清理过期的去重记录"""
        now = time.time()
        expired = [
            k for k, ts in self._recent_signals.items()
            if now - ts > max_age
        ]
        for k in expired:
            del self._recent_signals[k]
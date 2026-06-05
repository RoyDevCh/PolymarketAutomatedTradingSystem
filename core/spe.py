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
        self._signal_dedup_window: float = 60.0  # 60秒去重窗口 (Maker信号低频)

    def register_market(self, market: MarketInfo) -> None:
        """注册市场信息 (由 MDG 调用)"""
        self._markets[market.condition_id] = market
        self._condition_to_tokens[market.condition_id] = {
            "yes": market.yes_token_id,
            "no": market.no_token_id,
        }

    def on_orderbook_update(self, snapshot: OrderBookSnapshot) -> None:
        """MDG callback: orderbook snapshot received. v1.3 debug logging."""
        # v1.3 data flow debug
        if not hasattr(self, '_obu_count'):
            self._obu_count = 0
        self._obu_count += 1
        if self._obu_count <= 5:
            logger.info(
                "spe_obu_debug",
                token_id=snapshot.token_id[:16],
                condition_id=(snapshot.condition_id or "")[:16],
                has_asks=bool(snapshot.asks),
                has_bids=bool(snapshot.bids),
                registered_cids=len(self._condition_to_tokens),
            )

        # Update cache
        self._orderbooks[snapshot.token_id] = snapshot

        # Find condition_id
        condition_id = snapshot.condition_id
        if not condition_id:
            condition_id = self._find_condition(snapshot.token_id)
            if not condition_id:
                if self._obu_count <= 3:
                    logger.warning(
                        "spe_obu_no_condition",
                        token_id=snapshot.token_id[:16],
                        registered=len(self._condition_to_tokens),
                    )
                return

        tokens = self._condition_to_tokens.get(condition_id)
        if not tokens:
            if self._obu_count <= 3:
                logger.warning(
                    "spe_obu_no_tokens",
                    condition_id=condition_id[:20],
                    registered=len(self._condition_to_tokens),
                )
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
        核心套利评估 (v1.2 改进版)
        
        套利模式识别:
        
        模式 A — 经典双边 ASK 套利:
          buy YES at Ask(YES) + buy NO at Ask(NO)
          条件: Ask_YES + Ask_NO < 1
          利润: 1 - (Ask_YES + Ask_NO)
        
        模式 B — ASK+BID 交叉套利 (更常见但有 Leg Risk):
          buy YES at Ask(YES), sell NO at Bid(NO)
          条件: Ask_YES + Bid_NO < Ask_YES
          等价于 Ask_YES < 1 - Bid_NO = Ask_NO_implied
        
        v1.2 改进:
        1. 同时检测两种套利模式
        2. 深度诊断日志: 即使无套利也记录 BBO
        3. 低深度订单簿预警
        """
        if not yes_ob.asks and not yes_ob.bids and not no_ob.asks and not no_ob.bids:
            return  # 两边都空

        best_ask_yes = yes_ob.best_ask
        best_bid_yes = yes_ob.best_bid
        best_ask_no = no_ob.best_ask
        best_bid_no = no_ob.best_bid

        yes_depth = len(yes_ob.asks)
        no_depth = len(no_ob.asks)

        # ================================================================
        # 深度诊断日志 (每 100 个快照记录一次)
        # ================================================================
        signal_key = f"{condition_id[:16]}"
        now = time.time()
        last_diag = getattr(self, '_last_diag_ts', {}).get(signal_key, 0)
        if now - last_diag > 60:  # 每分钟最多一次诊断
            if not hasattr(self, '_last_diag_ts'):
                self._last_diag_ts = {}
            self._last_diag_ts[signal_key] = now
            
            ask_y = best_ask_yes.price if best_ask_yes else None
            bid_y = best_bid_yes.price if best_bid_yes else None
            ask_n = best_ask_no.price if best_ask_no else None
            bid_n = best_bid_no.price if best_bid_no else None
            
            logger.debug(
                "spe_bbo_diagnostic",
                condition_id=condition_id[:16],
                yes_ask=ask_y,
                yes_bid=bid_y,
                no_ask=ask_n,
                no_bid=bid_n,
                yes_depth=yes_depth,
                no_depth=no_depth,
            )
            
            # 低深度预警
            if yes_depth < 3 or no_depth < 3:
                logger.info(
                    "spe_low_depth",
                    condition_id=condition_id[:16],
                    yes_depth=yes_depth,
                    no_depth=no_depth,
                )

        # ================================================================
        # 模式 A: 双边 ASK 套利
        # buy YES at Ask + buy NO at Ask
        # 条件: Ask_YES + Ask_NO < 1
        # ================================================================
        if best_ask_yes and best_ask_no:
            theoretical_spread = 1.0 - (best_ask_yes.price + best_ask_no.price)

            if theoretical_spread > 0:
                # 理论上有空间, 计算 VWAP 穿透
                trade_size_usd = self.cfg.max_trade_size

                vwap_yes, size_yes, slip_yes = self._calculate_vwap(
                    yes_ob.asks, trade_size_usd
                )
                vwap_no, size_no, slip_no = self._calculate_vwap(
                    no_ob.asks, trade_size_usd
                )

                if vwap_yes <= 0 or vwap_no <= 0:
                    return

                actual_size = min(size_yes, size_no)
                if actual_size <= 0:
                    return

                # ============================================================
                # 利润计算 (v1.3 修正: VWAP 已含滑点, 不再双重扣除)
                #
                # 正确公式:
                #   net_profit_per_share = 1.0 - vwap_yes - vwap_no
                #   total_net_profit = net_profit_per_share * actual_size
                #
                # 原理: 购买 1 股 YES + 1 股 NO, 无论结果如何赔付 $1
                #   成本 = vwap_yes + vwap_no (已含滑点)
                #   利润 = 1 - vwap_yes - vwap_no (每股)
                #
                # 理论滑点 (仅供参考记录, 不影响利润计算):
                #   slippage_per_share = (vwap_yes - best_ask) + (vwap_no - best_ask)
                # ============================================================
                net_profit_per_share = 1.0 - vwap_yes - vwap_no
                total_net_profit = net_profit_per_share * actual_size

                # 理论滑点 (仅供参考)
                slippage_per_share = (vwap_yes - best_ask_yes.price) + (vwap_no - best_ask_no.price)
                total_slippage = slippage_per_share * actual_size

                # 理论最佳利润 (best ask 成交)
                best_ask_cost = best_ask_yes.price + best_ask_no.price

                logger.info(
                    "spe_arbitrage_calc",
                    condition_id=condition_id[:16],
                    vwap_yes=f"{vwap_yes:.4f}",
                    vwap_no=f"{vwap_no:.4f}",
                    best_ask_yes=f"{best_ask_yes.price:.4f}",
                    best_ask_no=f"{best_ask_no.price:.4f}",
                    actual_size=f"{actual_size:.4f}",
                    net_profit=f"${total_net_profit:.4f}",
                    slippage=f"${total_slippage:.4f}",
                    spread=f"{theoretical_spread:.4f}",
                )

                if total_net_profit < self.cfg.min_profit_threshold:
                    logger.info(
                        "spe_below_threshold",
                        condition_id=condition_id[:16],
                        net_profit=f"${total_net_profit:.4f}",
                        threshold=f"${self.cfg.min_profit_threshold}",
                        bbo_spread=f"{theoretical_spread:.4f}",
                        vwap_yes=f"{vwap_yes:.4f}",
                        vwap_no=f"{vwap_no:.4f}",
                    )
                    return

                self._generate_signal(
                    signal_type=SignalType.ARBITRAGE,
                    condition_id=condition_id,
                    yes_ob=yes_ob,
                    no_ob=no_ob,
                    vwap_yes=vwap_yes,
                    vwap_no=vwap_no,
                    actual_size=actual_size,
                    expected_profit=total_net_profit,
                    total_slippage=total_slippage,
                    total_cost=vwap_yes * actual_size + vwap_no * actual_size,
                    theoretical_spread=theoretical_spread,
                )
                return

        # ================================================================
        # 模式 B: ASK+BID 交叉套利 (较少见但更重要)
        # 买入被低估方, 卖出 (作为 maker) 被高估方
        # 条件: Ask(cheap) < 1 - Bid(expensive)
        # 例: YES_ask=0.45, NO_bid=0.48 > YES_ask < 1-0.48=0.52 ✓
        # ================================================================
        if best_ask_yes and best_bid_no:
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # 模式 B1: Maker 双边 Bid 套利 (转向一)
            # 如果 Bid_YES + Bid_NO + Margin < 1, 我们挂更低的 bid
            # 例: bid_yes=0.48, bid_no=0.48 → sum=0.96 → 我们挂 0.47/0.47
            # 终态赔付 1.0, 成本 0.94, 利润 0.06
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            if best_bid_yes and best_bid_no:
                bid_sum = best_bid_yes.price + best_bid_no.price
                if bid_sum < 1.0:
                    # 我们可以在当前 bid 下方挂单 (比 best_bid 低 1 tick)
                    # 利润 = 1.0 - (our_bid_yes + our_bid_no)
                    tick = 0.01
                    our_bid_yes = max(0.01, round(best_bid_yes.price - tick, 2))
                    our_bid_no = max(0.01, round(best_bid_no.price - tick, 2))
                    our_bid_sum = our_bid_yes + our_bid_no
                    if our_bid_sum > 0 and our_bid_sum < 1.0:
                        profit_per_share = 1.0 - our_bid_sum
                        budget = self.cfg.max_trade_size
                        min_shares = self.cfg.min_shares_per_leg
                        size = max(min_shares, round(budget / our_bid_sum, 2)) if our_bid_sum > 0 else 0
                        actual_cost = our_bid_sum * size  # may exceed MAX_TRADE_SIZE to meet min shares
                        total_profit = profit_per_share * size  # = (1.0 - our_bid_sum) * size
                        if total_profit >= self.cfg.min_profit_threshold:
                            logger.info(
                                "spe_maker_arb_detected",
                                condition_id=condition_id[:16],
                                bid_sum=bid_sum,
                                our_bid_sum=our_bid_sum,
                                profit_per_share=profit_per_share,
                                total_profit=f"${total_profit:.4f}",
                            )
                            self._generate_signal(
                                signal_type=SignalType.MAKER_ARB,
                                condition_id=condition_id,
                                yes_ob=yes_ob,
                                no_ob=no_ob,
                                vwap_yes=our_bid_yes,
                                vwap_no=our_bid_no,
                                actual_size=size,
                                expected_profit=total_profit,
                                total_slippage=0.0,  # maker: no slippage
                                total_cost=our_bid_sum * size,
                                theoretical_spread=1.0 - bid_sum,
                                order_type="GTX",
                            )
                            return

            # 模式 B2: Taker-Maker 交叉套利
            implied_no_ask = 1.0 - best_bid_no.price
            if best_ask_yes.price < implied_no_ask:
                potential_spread = implied_no_ask - best_ask_yes.price
                logger.info(
                    "spe_cross_arb_detected",
                    condition_id=condition_id[:16],
                    yes_ask=best_ask_yes.price,
                    no_bid=best_bid_no.price if best_bid_no else None,
                    implied_no_ask=implied_no_ask,
                    spread=potential_spread,
                    note="ASK+BID cross arb (maker strategy required)",
                )

        if best_ask_no and best_bid_yes:
            # 对称: 买 NO, YES_ask > 1 - YES_bid
            implied_yes_ask = 1.0 - best_bid_yes.price
            if best_ask_no.price < implied_yes_ask:
                potential_spread = implied_yes_ask - best_ask_no.price
                logger.info(
                    "spe_cross_arb_detected",
                    condition_id=condition_id[:16],
                    no_ask=best_ask_no.price,
                    yes_bid=best_bid_yes.price,
                    implied_yes_ask=implied_yes_ask,
                    spread=potential_spread,
                    note="NO ASK + YES BID cross arb (maker strategy)",
                )


    def _generate_signal(
        self,
        signal_type: SignalType,
        condition_id: str,
        yes_ob: OrderBookSnapshot,
        no_ob: OrderBookSnapshot,
        vwap_yes: float,
        vwap_no: float,
        actual_size: float,
        expected_profit: float,
        total_slippage: float,
        total_cost: float,
        theoretical_spread: float = 0.0,
        order_type: str = "GTC",
    ) -> None:
        """生成 TradeSignal 并推入执行队列"""
        now = time.time()
        # Maker signals: dedup by condition_id only (price drifts, don't use price in key)
        if signal_type == SignalType.MAKER_ARB:
            signal_key = f"maker:{condition_id}"
        else:
            signal_key = f"{condition_id}:{vwap_yes:.4f}:{vwap_no:.4f}"
        last_sent = self._recent_signals.get(signal_key, 0)
        if now - last_sent < self._signal_dedup_window:
            return

        self._recent_signals[signal_key] = now

        market = self._markets.get(condition_id, None)
        question = market.question if market else condition_id[:16]

        signal = TradeSignal(
            signal_id=str(uuid.uuid4()),
            signal_type=signal_type,
            condition_id=condition_id,
            market_question=question,
            yes_token_id=yes_ob.token_id,
            yes_price=vwap_yes,
            yes_size=actual_size,
            no_token_id=no_ob.token_id,
            no_price=vwap_no,
            no_size=actual_size,
            expected_profit=expected_profit,
            slippage_estimate=total_slippage,
            total_cost=total_cost,
            timestamp=now,
            priority=0,
            order_type=order_type,
        )

        try:
            self.signal_queue.put_nowait(signal)
            logger.info(
                "arbitrage_signal_generated",
                signal_id=signal.signal_id[:8],
                question=question[:50],
                vwap_yes=f"{vwap_yes:.4f}",
                vwap_no=f"{vwap_no:.4f}",
                size=actual_size,
                profit=f"${expected_profit:.4f}",
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
        """后台任务: 从队列中持续消费订单簿更新
        
        v1.2: 每60秒清理过期信号去重记录, 防止内存泄漏
        """
        _cleanup_counter = 0
        while True:
            try:
                snapshot: OrderBookSnapshot = await asyncio.wait_for(
                    queue.get(), timeout=1.0
                )
                self.on_orderbook_update(snapshot)
                _cleanup_counter += 1
                
                # 每 1000 次更新清理一次过期去重记录
                if _cleanup_counter >= 1000:
                    _cleanup_counter = 0
                    self.cleanup_stale_signals()
                    
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
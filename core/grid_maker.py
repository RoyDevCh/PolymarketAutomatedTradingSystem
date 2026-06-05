"""
Polymarket Phase 4 - 深度网格做市引擎 (Deep Grid Market Maker)

核心理念:
  不在 BBO 挂单（被知情交易者狙击），而退守深水区（5-15¢ away from BBO），
  捕捉恐慌性抛售带来的长尾噪音利润。

架构:
  GridMaker 接收 OrderBookSnapshot，计算波动率和安全挂单价位，
  输出 GridSignal（多档价位+数量），由 OEG 批量执行。

利润模型:
  市场价 0.50 → 我们在 0.35 和 0.20 挂买单
  恐慌抛售成交 → 0.35 买入 → 市场回归理性 → 0.50 卖出
  单笔利润 = 0.50 - 0.35 = $0.15/share (43% 收益率)

风险控制:
  1. 仅在 bid_sum < grid_min_profit_per_share 时挂单
  2. 通过波动率动态调整深度（高波动 → 退更远）
  3. 通过持仓上限控制单边敞口
  4. 通过关联市场对冲中和风险
"""

from __future__ import annotations

import time
import math
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
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


@dataclass
class GridLevel:
    """单档网格挂单参数"""
    side: str          # "YES" or "NO"
    price: float       # 挂单价格
    size: float        # 挂单数量 (shares)
    depth_ticks: int   # 距离 BBO 的 tick 数
    layer: str         # "shallow" 或 "deep"
    expected_profit_per_share: float  # 预期每股利润


@dataclass
class GridSignal:
    """深度网格做市信号 — 包含多档挂单"""
    signal_id: str
    condition_id: str
    market_question: str
    yes_token_id: str
    no_token_id: str
    levels: list[GridLevel]       # 所有挂单档位
    total_cost_usd: float         # 总投入成本
    expected_profit_usd: float    # 预期总利润
    bid_sum: float                 # 双边 bid 之和 (市价基准)
    our_bid_sum: float             # 我们的 bid 之和 (挂单后)
    volatility: float              # 当前波动率
    timestamp: float = field(default_factory=time.time)


class GridMaker:
    """
    深度网格做市引擎

    与 MakerStrategy (BBO 挂单) 的关键区别:
    1. 挂单位置: BBO → 退后 2-5 ticks (2-5¢)
    2. 利润要求: 2¢ → 8¢+ 每股
    3. 单笔大小: $2 → $1 shallow / $2 deep (分档)
    4. 持仓管理: 不持有 → 遇到填充后对冲或等待结算
    """

    def __init__(self, config=None):
        self.cfg = config or CONFIG.trading

        # 波动率历史: condition_id → deque of (timestamp, mid_price)
        self._price_history: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self.cfg.grid_volatility_window)
        )

        # 当前持仓: condition_id → {"yes": float, "no": float} (正=持有, 负=欠)
        self._inventory: dict[str, dict[str, float]] = defaultdict(
            lambda: {"yes": 0.0, "no": 0.0}
        )

        # 去重: 最近 N 秒内已发出的信号
        self._recent_signals: dict[str, float] = {}
        self._signal_dedup_window: float = 30.0  # 30秒去重窗口 (比 Maker 短)

        # 市场信息
        self._markets: dict[str, MarketInfo] = {}
        self._condition_to_tokens: dict[str, dict[str, str]] = {}

        # 统计
        self._signals_emitted: int = 0
        self._signals_rejected: int = 0

    def register_market(self, market: MarketInfo) -> None:
        """注册市场信息"""
        self._markets[market.condition_id] = market
        self._condition_to_tokens[market.condition_id] = {
            "yes": market.yes_token_id,
            "no": market.no_token_id,
        }

    def update_inventory(self, condition_id: str, side: str, fill_size: float) -> None:
        """
        更新持仓 — 当网格挂单被成交时调用
        
        Args:
            condition_id: 市场 ID
            side: "YES" 或 "NO"
            fill_size: 成交数量 (正数=买入)
        """
        inventory = self._inventory[condition_id]
        if side.upper() == "YES":
            inventory["yes"] += fill_size
        else:
            inventory["no"] += fill_size

        logger.info(
            "grid_inventory_updated",
            condition_id=condition_id[:16],
            yes_inventory=inventory["yes"],
            no_inventory=inventory["no"],
            total_exposure_usd=abs(inventory["yes"]) + abs(inventory["no"]),
        )

    def evaluate_grid(
        self,
        condition_id: str,
        yes_ob: OrderBookSnapshot,
        no_ob: OrderBookSnapshot,
    ) -> Optional[GridSignal]:
        """
        评估网格做市机会

        算法:
        1. 计算当前波动率 (价格标准差 / 均值)
        2. 根据波动率选择深度: 高波动 → 更远, 低波动 → 更近
        3. 计算 BBO 和我们的挂单位置
        4. 验证利润条件: our_bid_sum < 1.0 - min_profit
        5. 验证持仓上限: 单边不超过 hedge_max_inventory_usd
        6. 生成分层挂单信号
        """
        if not self.cfg.grid_enabled:
            return None

        best_bid_yes = yes_ob.best_bid
        best_bid_no = no_ob.best_bid
        best_ask_yes = yes_ob.best_ask
        best_ask_no = no_ob.best_ask

        if not best_bid_yes or not best_bid_no:
            return None

        # 1. 计算波动率
        mid_price_yes = (best_bid_yes.price + (best_ask_yes.price if best_ask_yes else best_bid_yes.price + 0.01)) / 2
        mid_price_no = (best_bid_no.price + (best_ask_no.price if best_ask_no else best_bid_no.price + 0.01)) / 2

        self._price_history[condition_id].append((time.time(), mid_price_yes))
        volatility = self._calculate_volatility(condition_id)

        # 2. 根据波动率调整深度
        tick = 0.01
        if volatility > 0.15:  # 高波动 (>15%)
            deep_ticks = self.cfg.grid_deep_ticks + 3  # 退更远
            shallow_ticks = self.cfg.grid_shallow_ticks + 2
        elif volatility > 0.08:  # 中波动 (8-15%)
            deep_ticks = self.cfg.grid_deep_ticks + 1
            shallow_ticks = self.cfg.grid_shallow_ticks + 1
        else:  # 低波动 (<8%) — 更适合做市
            deep_ticks = self.cfg.grid_deep_ticks
            shallow_ticks = self.cfg.grid_shallow_ticks

        # 3. 计算挂单价格
        # 浅水区: 略低于 BBO, 薄利
        our_shallow_bid_yes = max(0.01, round(best_bid_yes.price - shallow_ticks * tick, 2))
        our_shallow_bid_no = max(0.01, round(best_bid_no.price - shallow_ticks * tick, 2))

        # 深水区: 远低于 BBO, 厚利
        our_deep_bid_yes = max(0.01, round(best_bid_yes.price - deep_ticks * tick, 2))
        our_deep_bid_no = max(0.01, round(best_bid_no.price - deep_ticks * tick, 2))

        # 4. 验证利润条件
        # 浅水区: bid_sum < 1.0 - min_profit
        shallow_bid_sum = our_shallow_bid_yes + our_shallow_bid_no
        shallow_profit = 1.0 - shallow_bid_sum

        # 深水区: bid_sum < 1.0 - 2*min_profit (更高利润要求)
        deep_bid_sum = our_deep_bid_yes + our_deep_bid_no
        deep_profit = 1.0 - deep_bid_sum

        if shallow_profit < self.cfg.grid_min_profit_per_share:
            # 即使浅水区利润也不够
            if deep_profit < self.cfg.grid_min_profit_per_share:
                self._signals_rejected += 1
                return None

        # 5. 检查持仓限制
        inventory = self._inventory.get(condition_id, {"yes": 0.0, "no": 0.0})
        max_inv = self.cfg.hedge_max_inventory_usd if self.cfg.hedge_enabled else self.cfg.max_trade_size

        # 6. 构建分层挂单
        levels = []
        total_cost = 0.0
        total_expected_profit = 0.0

        # 浅水区挂单 (如果利润足够)
        if shallow_profit >= self.cfg.grid_min_profit_per_share:
            shallow_size_yes = self.cfg.grid_shallow_size_usd / our_shallow_bid_yes if our_shallow_bid_yes > 0 else 0
            shallow_size_no = self.cfg.grid_shallow_size_usd / our_shallow_bid_no if our_shallow_bid_no > 0 else 0

            # 检查持仓上限
            if abs(inventory["yes"]) + shallow_size_yes * our_shallow_bid_yes <= max_inv:
                levels.append(GridLevel(
                    side="YES",
                    price=our_shallow_bid_yes,
                    size=shallow_size_yes,
                    depth_ticks=shallow_ticks,
                    layer="shallow",
                    expected_profit_per_share=shallow_profit / 2,  # 大约一半概率成交
                ))
                total_cost += shallow_size_yes * our_shallow_bid_yes
                total_expected_profit += shallow_size_yes * shallow_profit / 2

            if abs(inventory["no"]) + shallow_size_no * our_shallow_bid_no <= max_inv:
                levels.append(GridLevel(
                    side="NO",
                    price=our_shallow_bid_no,
                    size=shallow_size_no,
                    depth_ticks=shallow_ticks,
                    layer="shallow",
                    expected_profit_per_share=shallow_profit / 2,
                ))
                total_cost += shallow_size_no * our_shallow_bid_no
                total_expected_profit += shallow_size_no * shallow_profit / 2

        # 深水区挂单 (如果利润足够)
        if deep_profit >= self.cfg.grid_min_profit_per_share * 1.5:  # 深水区要求 1.5x 利润
            deep_size_yes = self.cfg.grid_deep_size_usd / our_deep_bid_yes if our_deep_bid_yes > 0 else 0
            deep_size_no = self.cfg.grid_deep_size_usd / our_deep_bid_no if our_deep_bid_no > 0 else 0

            if abs(inventory["yes"]) + deep_size_yes * our_deep_bid_yes <= max_inv:
                levels.append(GridLevel(
                    side="YES",
                    price=our_deep_bid_yes,
                    size=deep_size_yes,
                    depth_ticks=deep_ticks,
                    layer="deep",
                    expected_profit_per_share=deep_profit / 3,  # 更低概率成交
                ))
                total_cost += deep_size_yes * our_deep_bid_yes
                total_expected_profit += deep_size_yes * deep_profit / 3

            if abs(inventory["no"]) + deep_size_no * our_deep_bid_no <= max_inv:
                levels.append(GridLevel(
                    side="NO",
                    price=our_deep_bid_no,
                    size=deep_size_no,
                    depth_ticks=deep_ticks,
                    layer="deep",
                    expected_profit_per_share=deep_profit / 3,
                ))
                total_cost += deep_size_no * our_deep_bid_no
                total_expected_profit += deep_size_no * deep_profit / 3

        if not levels:
            self._signals_rejected += 1
            return None

        # 去重
        now = time.time()
        signal_key = f"grid:{condition_id}"
        if signal_key in self._recent_signals:
            last_ts = self._recent_signals[signal_key]
            if now - last_ts < self._signal_dedup_window:
                return None
        self._recent_signals[signal_key] = now

        bid_sum = best_bid_yes.price + best_bid_no.price
        our_bid_sum = levels[0].price + levels[1].price if len(levels) >= 2 else 0

        signal = GridSignal(
            signal_id=f"grid-{uuid.uuid4().hex[:8]}",
            condition_id=condition_id,
            market_question=self._markets.get(condition_id, MarketInfo("", "", "", "")).question,
            yes_token_id=self._condition_to_tokens.get(condition_id, {}).get("yes", ""),
            no_token_id=self._condition_to_tokens.get(condition_id, {}).get("no", ""),
            levels=levels,
            total_cost_usd=total_cost,
            expected_profit_usd=total_expected_profit,
            bid_sum=bid_sum,
            our_bid_sum=our_bid_sum,
            volatility=volatility,
        )

        self._signals_emitted += 1
        logger.info(
            "grid_signal_emitted",
            condition_id=condition_id[:16],
            levels=len(levels),
            shallow_profit=f"${shallow_profit:.3f}/share",
            deep_profit=f"${deep_profit:.3f}/share",
            volatility=f"{volatility:.3f}",
            total_cost=f"${total_cost:.2f}",
            expected_profit=f"${total_expected_profit:.2f}",
            deep_ticks=deep_ticks,
            shallow_ticks=shallow_ticks,
        )

        return signal

    def _calculate_volatility(self, condition_id: str) -> float:
        """
        计算价格波动率 (标准差 / 均值)

        使用最近 N 个快照的中间价计算。
        高波动率 → 需要更远的挂单位置
        低波动率 → 可以更接近 BBO
        """
        history = self._price_history.get(condition_id)
        if not history or len(history) < 10:
            return 0.10  # 默认 10% 波动率

        prices = [p for _, p in history]
        if len(prices) < 2:
            return 0.10

        # 计算对数收益率的标准差
        returns = []
        for i in range(1, len(prices)):
            if prices[i-1] > 0 and prices[i] > 0:
                returns.append(math.log(prices[i] / prices[i-1]))

        if len(returns) < 5:
            return 0.10

        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        std = math.sqrt(variance)

        # 年化波动率 (假设每个快照 ~1秒)
        annualized = std * math.sqrt(86400)  # ~1秒间隔, 年化
        return min(annualized, 1.0)  # cap at 100%

    def get_stats(self) -> dict:
        """返回引擎统计信息"""
        return {
            "signals_emitted": self._signals_emitted,
            "signals_rejected": self._signals_rejected,
            "markets_tracked": len(self._condition_to_tokens),
            "price_histories": {k: len(v) for k, v in self._price_history.items()},
            "inventories": dict(self._inventory),
        }


# 需要导入 uuid
import uuid
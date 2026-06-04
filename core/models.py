"""
Polymarket 自动套利系统 - 核心数据模型定义
所有模块间通过这些标准化的 dataclass 进行数据流转
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


# ============================================================
# 枚举类型
# ============================================================

class Side(Enum):
    """订单方向"""
    YES = "YES"
    NO = "NO"


class OrderType(Enum):
    """订单类型"""
    GTC = "GTC"        # Good Till Cancelled
    GTX = "GTX"        # Good Till Crossing (只做 Maker)
    FOK = "FOK"        # Fill or Kill
    IOC = "IOC"        # Immediate or Cancel


class SignalType(Enum):
    """信号类型"""
    ARBITRAGE = auto()         # 套利信号
    HEDGE = auto()            # 对冲信号
    EMERGENCY_CLOSE = auto()  # 紧急平仓信号


class OrderStatus(Enum):
    """订单状态"""
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    MATCHED = "MATCHED"
    PARTIALLY_MATCHED = "PARTIALLY_MATCHED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CircuitBreakerType(Enum):
    """熔断类型"""
    LEG_RISK = auto()        # 单边敞口风险
    CONSECUTIVE_FAIL = auto()  # 连续失败
    SLIPPAGE_EXCEEDED = auto()  # 滑点超限
    NETWORK_TIMEOUT = auto()   # 网络超时


# ============================================================
# 市场数据结构
# ============================================================

@dataclass
class MarketInfo:
    """从 Gamma API 获取的市场元信息"""
    condition_id: str
    question: str
    yes_token_id: str
    no_token_id: str
    active: bool = True
    volume: float = 0.0
    liquidity: float = 0.0
    end_date_iso: str = ""


@dataclass
class PriceLevel:
    """订单簿单档价位"""
    price: float          # 价格 (0~1 区间)
    size: float           # 挂单量 (USD)

    @property
    def cost(self) -> float:
        """买入这一档所需成本"""
        return self.price * self.size


@dataclass
class OrderBookSnapshot:
    """订单簿快照 - MDG 输出的核心数据结构"""
    token_id: str
    condition_id: str
    timestamp: float = field(default_factory=time.time)
    asks: list[PriceLevel] = field(default_factory=list)  # 卖盘: 价格升序
    bids: list[PriceLevel] = field(default_factory=list)  # 买盘: 价格降序

    @property
    def best_ask(self) -> Optional[PriceLevel]:
        """最优卖价 (最低卖价)"""
        return self.asks[0] if self.asks else None

    @property
    def best_bid(self) -> Optional[PriceLevel]:
        """最优买价 (最高买价)"""
        return self.bids[0] if self.bids else None

    @property
    def spread(self) -> Optional[float]:
        """买卖价差"""
        if self.best_ask and self.best_bid:
            return self.best_ask.price - self.best_bid.price
        return None


# ============================================================
# 策略信号
# ============================================================

@dataclass
class TradeSignal:
    """SPE 输出的交易信号 - 传递给 OEG 执行"""
    signal_id: str
    signal_type: SignalType
    condition_id: str
    market_question: str

    # YES 腿参数
    yes_token_id: str
    yes_price: float        # 期望成交价
    yes_size: float          # 期望成交量 (USD)

    # NO 腿参数
    no_token_id: str
    no_price: float
    no_size: float

    # 期望值
    expected_profit: float   # 预期套利利润 (USD)
    slippage_estimate: float # 预估滑点
    total_cost: float        # 总投入成本

    # 元信息
    timestamp: float = field(default_factory=time.time)
    priority: int = 0       # 优先级, 0=最高


# ============================================================
# 订单与执行结果
# ============================================================

@dataclass
class OrderRequest:
    """OEG 构造的订单请求"""
    token_id: str
    side: Side
    price: float
    size: float
    order_type: OrderType = OrderType.GTC
    signal_id: str = ""


@dataclass
class ExecutionResult:
    """单腿执行结果"""
    signal_id: str
    token_id: str
    side: Side
    order_id: str = ""
    status: OrderStatus = OrderStatus.PENDING
    filled_size: float = 0.0
    avg_fill_price: float = 0.0
    slippage_actual: float = 0.0
    gas_cost: float = 0.0
    error_message: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class ArbitrageResult:
    """一笔套利的完整结果 (两腿)"""
    signal_id: str
    condition_id: str
    yes_result: ExecutionResult = field(default_factory=ExecutionResult)
    no_result: ExecutionResult = field(default_factory=ExecutionResult)
    realized_profit: float = 0.0
    is_complete: bool = False  # 两腿是否均已终态

    @property
    def has_leg_risk(self) -> bool:
        """检测是否存在单边敞口风险"""
        yes_ok = self.yes_result.status == OrderStatus.MATCHED
        no_ok = self.no_result.status == OrderStatus.MATCHED
        yes_fail = self.yes_result.status in (OrderStatus.FAILED, OrderStatus.CANCELLED)
        no_fail = self.no_result.status in (OrderStatus.FAILED, OrderStatus.CANCELLED)
        return (yes_ok and no_fail) or (no_ok and yes_fail)


# ============================================================
# 风控事件
# ============================================================

@dataclass
class CircuitBreakerEvent:
    """熔断器事件"""
    breaker_type: CircuitBreakerType
    condition_id: str
    message: str
    cooldown_until: float = 0.0  # 熔断解除的时间戳
    timestamp: float = field(default_factory=time.time)
"""
Polymarket 自动套利系统 - 核心模块包
"""

from core.config import CONFIG
from core.models import (
    ArbitrageResult,
    CircuitBreakerEvent,
    CircuitBreakerType,
    MarketInfo,
    OrderBookSnapshot,
    OrderRequest,
    OrderStatus,
    OrderType,
    PriceLevel,
    Side,
    SignalType,
    TradeSignal,
)
from core.clob_client import get_clob_client, ClobClientManager
from core.mdg import MarketDataGateway
from core.spe import StrategyPricingEngine
from core.oeg import OrderExecutionGateway
from core.rmc import RiskManagementCenter

__all__ = [
    "CONFIG",
    "ArbitrageResult",
    "CircuitBreakerEvent",
    "CircuitBreakerType",
    "MarketInfo",
    "OrderBookSnapshot",
    "OrderRequest",
    "OrderStatus",
    "OrderType",
    "PriceLevel",
    "Side",
    "SignalType",
    "TradeSignal",
    "get_clob_client",
    "ClobClientManager",
    "MarketDataGateway",
    "StrategyPricingEngine",
    "OrderExecutionGateway",
    "RiskManagementCenter",
]
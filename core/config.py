"""
Polymarket 自动套利系统 - 统一配置管理
从 .env 文件加载所有参数，提供类型安全的访问接口
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# 加载 .env (优先从项目根目录)
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path, override=True)


@dataclass(frozen=True)
class CLOBConfig:
    """CLOB API 配置"""
    api_url: str = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")
    ws_market_url: str = os.getenv("CLOB_WS_MARKET_URL", "wss://ws-subscriptions-clob.polymarket.com/ws/market")
    ws_user_url: str = os.getenv("CLOB_WS_USER_URL", "wss://ws-subscriptions-clob.polymarket.com/ws/user")
    api_key: str = os.getenv("API_KEY", "")
    api_secret: str = os.getenv("API_SECRET", "")
    api_passphrase: str = os.getenv("API_PASSPHRASE", "")


@dataclass(frozen=True)
class WalletConfig:
    """钱包 & 签名配置"""
    private_key: str = os.getenv("PRIVATE_KEY", "")
    rpc_url: str = os.getenv("RPC_URL", "https://polygon-rpc.com")
    chain_id: int = 137  # Polygon Mainnet


@dataclass(frozen=True)
class GammaConfig:
    """Gamma API 配置"""
    api_url: str = os.getenv("GAMMA_API_URL", "https://gamma-api.polymarket.com")
    poll_interval: int = 300  # 5 分钟轮询间隔 (秒)
    min_volume: float = 10_000.0  # 最低交易量过滤阈值
    min_liquidity: float = 5_000.0  # 最低流动性过滤阈值


@dataclass(frozen=True)
class TradingConfig:
    """交易参数配置"""
    max_trade_size: float = float(os.getenv("MAX_TRADE_SIZE", "2.0"))
    min_profit_threshold: float = float(os.getenv("MIN_PROFIT_THRESHOLD", "0.005"))
    max_slippage_pct: float = float(os.getenv("MAX_SLIPPAGE_PCT", "0.5")) / 100.0
    order_type: str = "GTC"


@dataclass(frozen=True)
class RiskConfig:
    """风控参数配置"""
    consecutive_fail_limit: int = int(os.getenv("CONSECUTIVE_FAIL_LIMIT", "3"))
    circuit_breaker_cooldown: int = int(os.getenv("CIRCUIT_BREAKER_COOLDOWN", "900"))


@dataclass(frozen=True)
class TelegramConfig:
    """Telegram 报警配置 (Phase 4)"""
    bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")


@dataclass(frozen=True)
class SystemConfig:
    """系统顶层配置聚合"""
    clob: CLOBConfig = field(default_factory=CLOBConfig)
    wallet: WalletConfig = field(default_factory=WalletConfig)
    gamma: GammaConfig = field(default_factory=GammaConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)

    # 数据库路径
    db_path: str = str(Path(__file__).resolve().parent.parent / "db" / "arbitrage.db")

    # 队列大小
    max_queue_size: int = 1000


def validate_config(cfg: SystemConfig) -> list[str]:
    """校验配置完整性, 返回错误列表"""
    errors = []
    if not cfg.wallet.private_key:
        errors.append("PRIVATE_KEY 未配置")
    if not cfg.clob.api_key:
        errors.append("API_KEY 未配置")
    if not cfg.clob.api_secret:
        errors.append("API_SECRET 未配置")
    if not cfg.clob.api_passphrase:
        errors.append("API_PASSPHRASE 未配置")
    if "polygon-rpc.com" in cfg.wallet.rpc_url:
        errors.append("RPC_URL 使用公共节点, 强烈建议配置 Alchemy/QuickNode 专属节点")
    return errors


# 全局配置单例
CONFIG = SystemConfig()
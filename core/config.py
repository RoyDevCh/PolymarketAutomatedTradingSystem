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
    wallet_address: str = os.getenv("WALLET_ADDRESS", "")
    deposit_wallet: str = os.getenv("DEPOSIT_WALLET", "")
    signature_type: int = int(os.getenv("SIGNATURE_TYPE", "3"))
    rpc_url: str = os.getenv("RPC_URL", "https://polygon-rpc.com")
    chain_id: int = 137  # Polygon Mainnet


@dataclass(frozen=True)
class GammaConfig:
    """Gamma API 配置"""
    api_url: str = os.getenv("GAMMA_API_URL", "https://gamma-api.polymarket.com")
    poll_interval: int = 300  # 5 分钟轮询间隔 (秒)
    min_volume: float = float(os.getenv("GAMMA_MIN_VOLUME", "1.0"))
    min_liquidity: float = float(os.getenv("GAMMA_MIN_LIQUIDITY", "1.0"))


@dataclass(frozen=True)
class SystemFlags:
    """系统运行标志"""
    dry_run: bool = field(default_factory=lambda: os.getenv("DRY_RUN", "false").lower() in ("1", "true", "yes"))


@dataclass(frozen=True)
class TradingConfig:
    """交易参数配置"""
    max_trade_size: float = float(os.getenv("MAX_TRADE_SIZE", "2.0"))
    min_profit_threshold: float = float(os.getenv("MIN_PROFIT_THRESHOLD", "0.005"))
    max_slippage_pct: float = float(os.getenv("MAX_SLIPPAGE_PCT", "0.5")) / 100.0
    order_type: str = "GTC"
    # ── Maker 策略约束 ──
    max_concurrent_markets: int = int(os.getenv("MAX_CONCURRENT_MARKETS", "2"))
    min_shares_per_leg: int = int(os.getenv("MIN_SHARES_PER_LEG", "5"))  # Polymarket 最低 5 股


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
    enabled: bool = os.getenv("TELEGRAM_ENABLED", "false").lower() in ("1", "true", "yes")
    heartbeat_interval_seconds: int = int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "3600"))


@dataclass(frozen=True)
class Phase3Config:
    """Phase 3 Go/No-Go auto-notification thresholds"""
    enabled: bool = os.getenv("PHASE3_NOTIFY_ENABLED", "true").lower() in ("1", "true", "yes")
    min_uptime_hours: float = float(os.getenv("PHASE3_MIN_UPTIME_HOURS", "48"))
    min_attempts: int = int(os.getenv("PHASE3_MIN_ATTEMPTS", "100"))
    max_leg_risk_rate: float = float(os.getenv("PHASE3_MAX_LEG_RISK_RATE", "0.05"))
    min_slippage_pass_rate: float = float(os.getenv("PHASE3_MIN_SLIPPAGE_PASS_RATE", "0.90"))
    check_interval_seconds: int = int(os.getenv("PHASE3_CHECK_INTERVAL_SECONDS", "3600"))
    ghost_pending_grace_seconds: int = int(os.getenv("PHASE3_GHOST_GRACE_SECONDS", "1800"))


@dataclass(frozen=True)
class SystemConfig:
    """系统顶层配置聚合"""
    clob: CLOBConfig = field(default_factory=CLOBConfig)
    wallet: WalletConfig = field(default_factory=WalletConfig)
    gamma: GammaConfig = field(default_factory=GammaConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    phase3: Phase3Config = field(default_factory=Phase3Config)
    flags: SystemFlags = field(default_factory=SystemFlags)

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
    if not cfg.wallet.deposit_wallet:
        errors.append("DEPOSIT_WALLET 未配置")
    if "polygon-rpc.com" in cfg.wallet.rpc_url:
        errors.append("RPC_URL 使用公共节点, 强烈建议配置 Alchemy/QuickNode 专属节点")
    return errors


# 全局配置单例
CONFIG = SystemConfig()
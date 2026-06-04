"""
Polymarket 自动套利系统 - 风控与记录中心 (RMC)

职责:
1. 熔断器 (Circuit Breaker):
   - 单边敞口熔断: YES成交NO失败 → 禁用该市场 + 触发平仓
   - 连败熔断: 连续N次失败 → 暂停 OEG 写权限
   - 滑点熔断: 实际滑点超过阈值 → 暂停交易
2. 持久化层:
   - 异步写入 SQLite, 记录每笔套利信号与执行结果
   - 定期导出盈亏报表
3.Telegram 报警 (Phase 4)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import aiosqlite
import structlog

from core.config import CONFIG
from core.models import (
    ArbitrageResult,
    CircuitBreakerEvent,
    CircuitBreakerType,
    ExecutionResult,
    OrderStatus,
    TradeSignal,
)

logger = structlog.get_logger(__name__)


@dataclass
class CircuitBreakerState:
    """熔断器状态"""
    is_active: bool = False
    breaker_type: Optional[CircuitBreakerType] = None
    cooldown_until: float = 0.0
    triggered_at: float = 0.0
    market_id: str = ""


class RiskManagementCenter:
    """
    风控与记录中心 (RMC)
    
    熔断机制架构:
    ┌──────────────────────────────────────────────────┐
    │  Level 1: 市场级熔断                               │
    │  - 单边敞口 → 禁用特定市场                          │
    │  - 滑点超限 → 禁用特定市场                          │
    │                                                     │
    │  Level 2: 系统级熔断                                │
    │  - 连续N次失败 → 暂停整个 OEG 写权限                 │
    │  - 网络异常 → 暂停交易                              │
    │                                                     │
    │  冷却期后自动恢复或需手动确认                        │
    └──────────────────────────────────────────────────┘
    """

    def __init__(self, oeg=None):
        self.cfg = CONFIG.risk
        self.oeg = oeg  # OEG 引用, 用于调用 disable_market

        # ---- SQLite 数据库 ----
        self._db: Optional[aiosqlite.Connection] = None
        self._db_path = CONFIG.db_path

        # ---- 熔断器状态 ----
        self._market_breakers: dict[str, CircuitBreakerState] = {}  # condition_id -> state
        self._system_breaker = CircuitBreakerState()

        # ---- 连败计数器 ----
        self._consecutive_fails: int = 0
        self._consecutive_success: int = 0

        # ---- 写权限控制 ----
        self._write_paused: bool = False
        self._write_pause_until: float = 0.0

    # ================================================================
    # 数据库初始化
    # ================================================================

    async def init_db(self) -> None:
        """初始化 SQLite 数据库和表结构"""
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")

        # 交易日志表
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS trade_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                signal_id TEXT NOT NULL,
                condition_id TEXT NOT NULL,
                market_question TEXT,
                yes_token_id TEXT,
                no_token_id TEXT,
                yes_price REAL,
                no_price REAL,
                yes_size REAL,
                no_size REAL,
                expected_profit REAL,
                realized_profit REAL,
                yes_order_id TEXT,
                no_order_id TEXT,
                yes_status TEXT,
                no_status TEXT,
                yes_fill_price REAL,
                no_fill_price REAL,
                yes_filled_size REAL,
                no_filled_size REAL,
                slippage_estimate REAL,
                has_leg_risk INTEGER DEFAULT 0,
                gas_cost REAL DEFAULT 0.0
            )
        """)

        # 熔断事件表
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS circuit_breaker_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                breaker_type TEXT NOT NULL,
                condition_id TEXT,
                message TEXT,
                cooldown_until REAL
            )
        """)

        # 信号统计表
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS signal_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                total_signals INTEGER DEFAULT 0,
                total_arbitrages INTEGER DEFAULT 0,
                total_profit REAL DEFAULT 0.0,
                total_leg_risks INTEGER DEFAULT 0,
                avg_slippage REAL DEFAULT 0.0
            )
        """)

        await self._db.commit()
        logger.info("rmc_db_initialized", path=self._db_path)

    async def close_db(self) -> None:
        """关闭数据库连接"""
        if self._db:
            await self._db.close()
            logger.info("rmc_db_closed")

    # ================================================================
    # 交易结果处理
    # ================================================================

    async def on_arbitrage_result(self, result: ArbitrageResult) -> None:
        """
        接收 OEG 的执行结果, 执行风控检查和日志记录
        
        流程:
        1. 记录到 SQLite
        2. 检查单边敞口风控
        3. 更新连败计数器
        4. 检查是否触发熔断
        """
        # ---- 记录日志 ----
        await self._log_result(result)

        # ---- 单边敞口检测 ----
        if result.has_leg_risk:
            await self._trigger_leg_risk_breaker(result)

        # ---- 更新连败计数 ----
        yes_ok = result.yes_result.status == OrderStatus.MATCHED
        no_ok = result.no_result.status == OrderStatus.MATCHED
        both_ok = yes_ok and no_ok

        if both_ok:
            self._consecutive_fails = 0
            self._consecutive_success += 1
        else:
            self._consecutive_fails += 1
            self._consecutive_success = 0

        # ---- 连败熔断检查 ----
        if self._consecutive_fails >= self.cfg.consecutive_fail_limit:
            await self._trigger_consecutive_fail_breaker()

        logger.info(
            "rmc_result_processed",
            signal_id=result.signal_id[:8],
            profit=f"${result.realized_profit:.4f}",
            leg_risk=result.has_leg_risk,
            consecutive_fails=self._consecutive_fails,
        )

    # ================================================================
    # 熔断器机制
    # ================================================================

    async def _trigger_leg_risk_breaker(self, result: ArbitrageResult) -> None:
        """
        单边敞口熔断
        
        动作:
        1. 禁用该市场 (condition_id) 的后续交易
        2. 记录熔断事件
        3. 报警 (Phase 4: Telegram)
        """
        condition_id = result.condition_id

        breaker = CircuitBreakerState(
            is_active=True,
            breaker_type=CircuitBreakerType.LEG_RISK,
            cooldown_until=time.time() + self.cfg.circuit_breaker_cooldown,
            triggered_at=time.time(),
            market_id=condition_id,
        )
        self._market_breakers[condition_id] = breaker

        # 通知 OEG 禁用该市场
        if self.oeg:
            self.oeg.disable_market(condition_id)

        # 记录熔断事件
        event = CircuitBreakerEvent(
            breaker_type=CircuitBreakerType.LEG_RISK,
            condition_id=condition_id,
            message=f"Leg risk detected: YES={result.yes_result.status.value}, NO={result.no_result.status.value}",
            cooldown_until=breaker.cooldown_until,
        )
        await self._log_circuit_breaker(event)

        logger.critical(
            "CIRCUIT_BREAKER_TRIGGERED",
            type="LEG_RISK",
            condition_id=condition_id[:16],
            cooldown_seconds=self.cfg.circuit_breaker_cooldown,
        )

        # Phase 4: 触发紧急平仓逻辑
        # await self._emergency_close_position(result)

    async def _trigger_consecutive_fail_breaker(self) -> None:
        """
        连败熔断
        
        动作:
        1. 暂停 OEG 写权限 15 分钟
        2. 记录熔断事件
        """
        self._write_paused = True
        self._write_pause_until = time.time() + self.cfg.circuit_breaker_cooldown

        self._system_breaker = CircuitBreakerState(
            is_active=True,
            breaker_type=CircuitBreakerType.CONSECUTIVE_FAIL,
            cooldown_until=self._write_pause_until,
            triggered_at=time.time(),
        )

        event = CircuitBreakerEvent(
            breaker_type=CircuitBreakerType.CONSECUTIVE_FAIL,
            condition_id="SYSTEM",
            message=f"Consecutive fails: {self._consecutive_fails}, pausing for {self.cfg.circuit_breaker_cooldown}s",
            cooldown_until=self._write_pause_until,
        )
        await self._log_circuit_breaker(event)

        logger.critical(
            "CIRCUIT_BREAKER_TRIGGERED",
            type="CONSECUTIVE_FAIL",
            consecutive_fails=self._consecutive_fails,
            cooldown_seconds=self.cfg.circuit_breaker_cooldown,
        )

    async def check_and_recover_breakers(self) -> None:
        """定期检查熔断器是否已过冷却期, 自动恢复"""
        now = time.time()

        # 检查系统级熔断
        if self._system_breaker.is_active and now >= self._system_breaker.cooldown_until:
            self._system_breaker.is_active = False
            self._write_paused = False
            self._consecutive_fails = 0
            logger.info("system_breaker_recovered")

        # 检查市场级熔断
        recovered_markets = []
        for cid, breaker in self._market_breakers.items():
            if breaker.is_active and now >= breaker.cooldown_until:
                breaker.is_active = False
                if self.oeg:
                    self.oeg.enable_market(cid)
                recovered_markets.append(cid[:16])

        if recovered_markets:
            logger.info("market_breakers_recovered", markets=recovered_markets)

    @property
    def is_write_paused(self) -> bool:
        """OEG 写权限是否被暂停"""
        return self._write_paused

    def is_market_paused(self, condition_id: str) -> bool:
        """指定市场是否被暂停"""
        breaker = self._market_breakers.get(condition_id)
        if not breaker:
            return False
        if breaker.is_active and time.time() < breaker.cooldown_until:
            return True
        return False

    # ================================================================
    # 持久化层
    # ================================================================

    async def _log_result(self, result: ArbitrageResult) -> None:
        """将套利结果写入 SQLite"""
        if not self._db:
            return

        try:
            await self._db.execute(
                """
                INSERT INTO trade_log (
                    timestamp, signal_id, condition_id, market_question,
                    yes_token_id, no_token_id,
                    yes_price, no_price, yes_size, no_size,
                    expected_profit, realized_profit,
                    yes_order_id, no_order_id,
                    yes_status, no_status,
                    yes_fill_price, no_fill_price,
                    yes_filled_size, no_filled_size,
                    slippage_estimate, has_leg_risk
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    time.time(),
                    result.signal_id,
                    result.condition_id,
                    "",  # market_question 需要从 signal 填充
                    result.yes_result.token_id,
                    result.no_result.token_id,
                    0.0,  # from signal, 需在 on_arbitrage_result 中补充
                    0.0,
                    result.yes_result.filled_size,
                    result.no_result.filled_size,
                    0.0,
                    result.realized_profit,
                    result.yes_result.order_id,
                    result.no_result.order_id,
                    result.yes_result.status.value,
                    result.no_result.status.value,
                    result.yes_result.avg_fill_price,
                    result.no_result.avg_fill_price,
                    result.yes_result.filled_size,
                    result.no_result.filled_size,
                    0.0,  # slippage from signal
                    1 if result.has_leg_risk else 0,
                ),
            )
            await self._db.commit()
        except Exception as e:
            logger.error("rmc_log_error", error=str(e))

    async def _log_circuit_breaker(self, event: CircuitBreakerEvent) -> None:
        """将熔断事件写入 SQLite"""
        if not self._db:
            return

        try:
            await self._db.execute(
                """
                INSERT INTO circuit_breaker_log (
                    timestamp, breaker_type, condition_id, message, cooldown_until
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.timestamp,
                    event.breaker_type.name,
                    event.condition_id,
                    event.message,
                    event.cooldown_until,
                ),
            )
            await self._db.commit()
        except Exception as e:
            logger.error("rmc_breaker_log_error", error=str(e))

    # ================================================================
    # 报表生成 (Phase 2 影子系统用)
    # ================================================================

    async def generate_profit_report(self, hours: int = 48) -> dict:
        """生成最近 N 小时的盈亏报表"""
        if not self._db:
            return {}

        cutoff = time.time() - (hours * 3600)

        try:
            cursor = await self._db.execute(
                """
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN realized_profit > 0 THEN 1 ELSE 0 END) as winning_trades,
                    SUM(realized_profit) as total_profit,
                    AVG(slippage_estimate) as avg_slippage,
                    SUM(CASE WHEN has_leg_risk = 1 THEN 1 ELSE 0 END) as leg_risk_count
                FROM trade_log
                WHERE timestamp > ?
                """,
                (cutoff,),
            )
            row = await cursor.fetchone()

            return {
                "total_trades": row[0] or 0,
                "winning_trades": row[1] or 0,
                "total_profit": row[2] or 0.0,
                "avg_slippage": row[3] or 0.0,
                "leg_risk_count": row[4] or 0,
                "hours": hours,
            }
        except Exception as e:
            logger.error("report_generation_error", error=str(e))
            return {}

    # ================================================================
    # 后台维护任务
    # ================================================================

    async def maintenance_loop(self) -> None:
        """定期维护: 熔断器恢复检查, 统计聚合"""
        while True:
            try:
                await self.check_and_recover_breakers()
                await asyncio.sleep(30)  # 每30秒检查一次
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("rmc_maintenance_error", error=str(e))
                await asyncio.sleep(10)
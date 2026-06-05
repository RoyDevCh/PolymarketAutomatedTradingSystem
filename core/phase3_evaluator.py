"""Phase 3 Go/No-Go evaluation for automated pass notification."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import aiosqlite

from core.config import CONFIG

TERMINAL_STATUSES = frozenset(
    {"MATCHED", "CONFIRMED", "FAILED", "CANCELLED", "TRADE_FAILED", "EXPIRED"}
)
NON_TERMINAL_STATUSES = frozenset({"PENDING", "RETRYING", "LIVE", "OPEN"})


@dataclass
class Phase3CheckResult:
    """Outcome of a single Go/No-Go criterion."""

    name: str
    passed: bool
    detail: str


@dataclass
class Phase3Evaluation:
    """Full Phase 3 evaluation snapshot."""

    passed: bool
    ready: bool  # duration/attempt gate met
    uptime_hours: float
    dual_leg_attempts: int
    ghost_pending: int
    leg_risk_count: int
    leg_risk_rate: float
    leg_risk_breakers: int
    slippage_pass_rate: float
    slippage_samples: int
    net_pnl: float
    checks: list[Phase3CheckResult] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "ready": self.ready,
            "uptime_hours": round(self.uptime_hours, 2),
            "dual_leg_attempts": self.dual_leg_attempts,
            "ghost_pending": self.ghost_pending,
            "leg_risk_count": self.leg_risk_count,
            "leg_risk_rate": round(self.leg_risk_rate, 4),
            "leg_risk_breakers": self.leg_risk_breakers,
            "slippage_pass_rate": round(self.slippage_pass_rate, 4),
            "slippage_samples": self.slippage_samples,
            "net_pnl": round(self.net_pnl, 4),
            "blockers": self.blockers,
        }


async def evaluate_phase3(
    db: aiosqlite.Connection,
    *,
    started_at: float,
    window_start: float | None = None,
) -> Phase3Evaluation:
    """Evaluate Phase 3 Go/No-Go criteria against trade_log since window_start."""
    cfg = CONFIG.phase3
    trading = CONFIG.trading
    now = time.time()
    window = window_start if window_start is not None else started_at
    uptime_hours = max(0.0, (now - started_at) / 3600.0)

    params = (window,)

    cursor = await db.execute(
        """
        SELECT
            yes_order_id, no_order_id,
            yes_status, no_status,
            yes_price, no_price,
            yes_fill_price, no_fill_price,
            realized_profit, has_leg_risk,
            condition_id, timestamp
        FROM trade_log
        WHERE timestamp >= ?
        """,
        params,
    )
    rows = await cursor.fetchall()

    dual_leg_attempts = 0
    ghost_pending = 0
    leg_risk_count = 0
    slippage_ok = 0
    slippage_samples = 0
    net_pnl = 0.0
    leg_risk_condition_ids: list[str] = []

    ghost_cutoff = now - cfg.ghost_pending_grace_seconds

    for row in rows:
        (
            yes_oid,
            no_oid,
            yes_status,
            no_status,
            yes_price,
            no_price,
            yes_fill,
            no_fill,
            realized_profit,
            has_leg_risk,
            condition_id,
            ts,
        ) = row

        if yes_oid and no_oid:
            dual_leg_attempts += 1

        net_pnl += realized_profit or 0.0

        if has_leg_risk:
            leg_risk_count += 1
            if condition_id:
                leg_risk_condition_ids.append(condition_id)

        for status, oid, ts_val in (
            (yes_status, yes_oid, ts),
            (no_status, no_oid, ts),
        ):
            if not oid:
                continue
            if status in NON_TERMINAL_STATUSES and ts_val < ghost_cutoff:
                ghost_pending += 1

        deviations: list[float] = []
        if yes_price and yes_fill and yes_price > 0:
            deviations.append(abs(yes_fill - yes_price) / yes_price)
        if no_price and no_fill and no_price > 0:
            deviations.append(abs(no_fill - no_price) / no_price)
        if deviations:
            slippage_samples += 1
            if max(deviations) <= trading.max_slippage_pct:
                slippage_ok += 1

    leg_risk_rate = (
        leg_risk_count / dual_leg_attempts if dual_leg_attempts > 0 else 0.0
    )

    cb_cursor = await db.execute(
        """
        SELECT COUNT(*) FROM circuit_breaker_log
        WHERE timestamp >= ? AND breaker_type = 'LEG_RISK'
        """,
        params,
    )
    leg_risk_breakers = (await cb_cursor.fetchone())[0] or 0

    slippage_pass_rate = (
        slippage_ok / slippage_samples if slippage_samples > 0 else 1.0
    )

    ready = (
        uptime_hours >= cfg.min_uptime_hours
        or dual_leg_attempts >= cfg.min_attempts
    )

    checks: list[Phase3CheckResult] = []
    blockers: list[str] = []

    def _add(name: str, ok: bool, detail: str) -> None:
        checks.append(Phase3CheckResult(name=name, passed=ok, detail=detail))
        if not ok:
            blockers.append(f"{name}: {detail}")

    _add(
        "duration_gate",
        ready,
        f"uptime={uptime_hours:.1f}h (need {cfg.min_uptime_hours}h) "
        f"or attempts={dual_leg_attempts} (need {cfg.min_attempts})",
    )

    if ready:
        _add(
            "no_ghost_orders",
            ghost_pending == 0,
            f"ghost_pending={ghost_pending}",
        )
        _add(
            "leg_risk_rate",
            dual_leg_attempts == 0 or leg_risk_rate < cfg.max_leg_risk_rate,
            f"rate={leg_risk_rate:.2%} (max {cfg.max_leg_risk_rate:.0%}), "
            f"count={leg_risk_count}/{dual_leg_attempts}",
        )
        breaker_ok = leg_risk_count == 0 or leg_risk_breakers >= leg_risk_count
        _add(
            "circuit_breaker_on_leg_risk",
            breaker_ok,
            f"leg_risks={leg_risk_count}, LEG_RISK breakers={leg_risk_breakers}",
        )
        slip_ok = (
            slippage_samples == 0
            or slippage_pass_rate >= cfg.min_slippage_pass_rate
        )
        _add(
            "slippage_control",
            slip_ok,
            f"pass_rate={slippage_pass_rate:.1%} "
            f"(need {cfg.min_slippage_pass_rate:.0%}), samples={slippage_samples}",
        )
        _add(
            "positive_pnl",
            net_pnl > 0,
            f"net_pnl=${net_pnl:.4f}",
        )

    passed = ready and all(c.passed for c in checks)

    return Phase3Evaluation(
        passed=passed,
        ready=ready,
        uptime_hours=uptime_hours,
        dual_leg_attempts=dual_leg_attempts,
        ghost_pending=ghost_pending,
        leg_risk_count=leg_risk_count,
        leg_risk_rate=leg_risk_rate,
        leg_risk_breakers=leg_risk_breakers,
        slippage_pass_rate=slippage_pass_rate,
        slippage_samples=slippage_samples,
        net_pnl=net_pnl,
        checks=checks,
        blockers=blockers,
    )

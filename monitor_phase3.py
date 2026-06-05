#!/usr/bin/env python3
"""
Phase 3 Go/No-Go Monitor — SQLite-backed health check across 4 dimensions.

Dimensions:
  1. FillTracker status   — both legs reach MATCHED/CONFIRMED
  2. Leg risk / CB        — no recent leg-risk trades or circuit breakers
  3. Slippage deviation   — fill vs expected price within threshold
  4. PnL                  — daily PnL from v_daily_pnl

Usage:
  python monitor_phase3.py              # single snapshot
  python monitor_phase3.py --watch 30   # refresh every 30s
  python monitor_phase3.py --db path    # custom DB path
  python monitor_phase3.py --hours 24   # lookback window
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.config import CONFIG

DEFAULT_DB = CONFIG.db_path
DEFAULT_HOURS = 24
MAX_SLIPPAGE_PCT = float(os.getenv("MAX_SLIPPAGE_PCT", "0.5")) / 100.0
MAX_LEG_RISKS = int(os.getenv("PHASE3_MAX_LEG_RISKS", "0"))
MAX_CB_EVENTS = int(os.getenv("PHASE3_MAX_CB_EVENTS", "0"))


@dataclass
class DimensionResult:
    name: str
    status: str  # GO | NO-GO | WARN | N/A
    detail: str
    metric: str = ""


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def check_fill_tracker(conn: sqlite3.Connection, cutoff: float) -> DimensionResult:
    """Both legs should reach MATCHED (or better) after WS confirmation."""
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN yes_status IN ('MATCHED', 'CONFIRMED') AND no_status IN ('MATCHED', 'CONFIRMED') THEN 1 ELSE 0 END) AS both_ok,
            SUM(CASE WHEN yes_status IN ('FAILED', 'CANCELLED') OR no_status IN ('FAILED', 'CANCELLED') THEN 1 ELSE 0 END) AS failed
        FROM trade_log
        WHERE timestamp > ?
        """,
        (cutoff,),
    ).fetchone()

    total = row["total"] or 0
    both_ok = row["both_ok"] or 0
    failed = row["failed"] or 0

    if total == 0:
        return DimensionResult("FillTracker", "WARN", "No trades in lookback window", "0 trades")

    rate = both_ok / total
    if failed > 0:
        status = "NO-GO"
        detail = f"{failed} trade(s) with FAILED/CANCELLED leg(s)"
    elif rate >= 0.95:
        status = "GO"
        detail = f"{both_ok}/{total} trades fully matched ({rate:.0%})"
    elif rate >= 0.80:
        status = "WARN"
        detail = f"{both_ok}/{total} trades fully matched ({rate:.0%})"
    else:
        status = "NO-GO"
        detail = f"Only {both_ok}/{total} trades fully matched ({rate:.0%})"

    return DimensionResult("FillTracker", status, detail, f"{both_ok}/{total}")


def check_leg_risk_cb(conn: sqlite3.Connection, cutoff: float) -> DimensionResult:
    """Leg-risk trades and circuit-breaker events should be absent."""
    leg_row = conn.execute(
        "SELECT COUNT(*) AS n FROM trade_log WHERE timestamp > ? AND has_leg_risk = 1",
        (cutoff,),
    ).fetchone()
    leg_risks = leg_row["n"] or 0

    cb_row = conn.execute(
        "SELECT COUNT(*) AS n FROM circuit_breaker_log WHERE timestamp > ?",
        (cutoff,),
    ).fetchone()
    cb_events = cb_row["n"] or 0

    active_cb = conn.execute(
        "SELECT breaker_type, condition_id, message FROM circuit_breaker_log WHERE cooldown_until > ? ORDER BY timestamp DESC LIMIT 3",
        (time.time(),),
    ).fetchall()

    if leg_risks > MAX_LEG_RISKS or cb_events > MAX_CB_EVENTS:
        status = "NO-GO"
    elif leg_risks == 0 and cb_events == 0:
        status = "GO"
    else:
        status = "WARN"

    parts = [f"leg_risks={leg_risks}", f"cb_events={cb_events}"]
    if active_cb:
        parts.append(f"active_cb={len(active_cb)}")
    detail = ", ".join(parts)
    if active_cb:
        detail += " | " + "; ".join(
            f"{r['breaker_type']}@{str(r['condition_id'])[:12]}" for r in active_cb
        )

    return DimensionResult("LegRisk/CB", status, detail, f"lr={leg_risks} cb={cb_events}")


def check_slippage_deviation(conn: sqlite3.Connection, cutoff: float) -> DimensionResult:
    """Compare fill prices vs signal prices; flag excessive deviation."""
    rows = conn.execute(
        """
        SELECT yes_price, no_price, yes_fill_price, no_fill_price
        FROM trade_log
        WHERE timestamp > ?
          AND yes_fill_price IS NOT NULL AND yes_fill_price > 0
          AND no_fill_price IS NOT NULL AND no_fill_price > 0
        """,
        (cutoff,),
    ).fetchall()

    if not rows:
        return DimensionResult("Slippage", "WARN", "No fills with prices in lookback", "n=0")

    deviations = []
    for r in rows:
        if r["yes_price"] and r["yes_price"] > 0:
            deviations.append(abs(r["yes_fill_price"] - r["yes_price"]) / r["yes_price"])
        if r["no_price"] and r["no_price"] > 0:
            deviations.append(abs(r["no_fill_price"] - r["no_price"]) / r["no_price"])

    if not deviations:
        return DimensionResult("Slippage", "WARN", "Could not compute deviations", "n=0")

    avg_dev = sum(deviations) / len(deviations)
    max_dev = max(deviations)

    if max_dev > MAX_SLIPPAGE_PCT * 2:
        status = "NO-GO"
    elif avg_dev > MAX_SLIPPAGE_PCT:
        status = "WARN"
    else:
        status = "GO"

    detail = f"avg={avg_dev*100:.3f}% max={max_dev*100:.3f}% (limit={MAX_SLIPPAGE_PCT*100:.2f}%)"
    return DimensionResult("Slippage", status, detail, f"avg={avg_dev*100:.3f}%")


def check_pnl(conn: sqlite3.Connection) -> DimensionResult:
    """Daily PnL from v_daily_pnl view."""
    try:
        row = conn.execute(
            """
            SELECT trade_date, total_trades, total_profit, winning_trades, leg_risks
            FROM v_daily_pnl
            ORDER BY trade_date DESC
            LIMIT 1
            """
        ).fetchone()
    except sqlite3.OperationalError as e:
        return DimensionResult("PnL", "N/A", f"v_daily_pnl unavailable: {e}", "")

    if not row:
        return DimensionResult("PnL", "WARN", "No PnL data yet", "0 trades")

    profit = row["total_profit"] or 0.0
    trades = row["total_trades"] or 0
    wins = row["winning_trades"] or 0

    if trades == 0:
        status = "WARN"
    elif profit >= 0:
        status = "GO"
    else:
        status = "NO-GO"

    detail = f"{row['trade_date']}: ${profit:.4f} ({wins}/{trades} wins, leg_risks={row['leg_risks'] or 0})"
    return DimensionResult("PnL", status, detail, f"${profit:.4f}")


def run_checks(db_path: str, hours: int) -> tuple[list[DimensionResult], str]:
    cutoff = time.time() - hours * 3600
    conn = _connect(db_path)
    try:
        dims = [
            check_fill_tracker(conn, cutoff),
            check_leg_risk_cb(conn, cutoff),
            check_slippage_deviation(conn, cutoff),
            check_pnl(conn),
        ]
    finally:
        conn.close()

    statuses = [d.status for d in dims]
    if "NO-GO" in statuses:
        overall = "NO-GO"
    elif "WARN" in statuses or "N/A" in statuses:
        overall = "WARN"
    else:
        overall = "GO"

    return dims, overall


def print_report(dims: list[DimensionResult], overall: str, db_path: str, hours: int) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 60)
    print(f"  Phase 3 Go/No-Go Monitor  |  {ts}")
    print(f"  DB: {db_path}  |  lookback: {hours}h")
    print("=" * 60)
    for d in dims:
        icon = {"GO": "[GO]", "NO-GO": "[!!]", "WARN": "[??]", "N/A": "[--]"}.get(d.status, "[??]")
        print(f"  {icon} {d.name:16s} {d.status:6s}  {d.detail}")
    print("-" * 60)
    print(f"  OVERALL: {overall}")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 3 SQLite Go/No-Go monitor")
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    parser.add_argument("--hours", type=int, default=DEFAULT_HOURS, help="Lookback hours")
    parser.add_argument("--watch", type=int, default=0, metavar="N", help="Refresh every N seconds")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"ERROR: database not found: {args.db}")
        sys.exit(2)

    if args.watch > 0:
        try:
            while True:
                dims, overall = run_checks(args.db, args.hours)
                print_report(dims, overall, args.db, args.hours)
                print(f"\nRefreshing in {args.watch}s (Ctrl+C to stop)...\n")
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\nMonitor stopped.")
    else:
        dims, overall = run_checks(args.db, args.hours)
        print_report(dims, overall, args.db, args.hours)
        if overall == "NO-GO":
            sys.exit(1)


if __name__ == "__main__":
    main()

# Remote SSH checks: python monitor_status.py --password <ssh_pass>

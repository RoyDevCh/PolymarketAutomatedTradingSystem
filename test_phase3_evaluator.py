#!/usr/bin/env python3
"""Dry-run Phase 3 Go/No-Go evaluation against local/remote SQLite."""
from __future__ import annotations

import asyncio
import sys
import time

import aiosqlite

from core.config import CONFIG
from core.phase3_evaluator import evaluate_phase3


async def main() -> int:
    started_at = time.time() - 6 * 3600
    async with aiosqlite.connect(CONFIG.db_path) as db:
        ev = await evaluate_phase3(db, started_at=started_at)
    print("Phase 3 evaluation:")
    print(f"  passed={ev.passed} ready={ev.ready}")
    print(f"  uptime={ev.uptime_hours:.1f}h attempts={ev.dual_leg_attempts}")
    print(f"  ghost={ev.ghost_pending} leg_risk={ev.leg_risk_rate:.1%} pnl=${ev.net_pnl:.4f}")
    for c in ev.checks:
        mark = "OK" if c.passed else "FAIL"
        print(f"  [{mark}] {c.name}: {c.detail}")
    return 0 if ev.passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

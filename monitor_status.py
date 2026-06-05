#!/usr/bin/env python3
"""SSH remote monitor for polymarket-arb (run locally)."""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone

HOST = "192.168.3.117"
USER = "roy"
REMOTE = "/home/roy/polymarket-arb"


def ssh_run(host: str, user: str, password: str | None, cmd: str) -> str:
    if password:
        import paramiko

        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(host, username=user, password=password, timeout=20)
        _, stdout, stderr = c.exec_command(cmd, timeout=120)
        out = (stdout.read() + stderr.read()).decode("utf-8", errors="replace")
        c.close()
        return out
    proc = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", f"{user}@{host}", cmd],
        capture_output=True,
        text=True,
    )
    return proc.stdout + proc.stderr


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default=HOST)
    p.add_argument("--user", default=USER)
    p.add_argument("--password", default=None)
    p.add_argument("--remote", default=REMOTE)
    args = p.parse_args()
    r = args.remote

    py_db = (
        f"cd {r} && source venv/bin/activate && python3 -c \""
        "import sqlite3; c=sqlite3.connect('db/arbitrage.db'); "
        "print('trade_count', c.execute('SELECT COUNT(*) FROM trade_log').fetchone()[0]); "
        "rows=c.execute('SELECT * FROM v_daily_pnl LIMIT 5').fetchall(); "
        "print('v_daily_pnl', rows if rows else 'empty')\""
    )
    checks = {
        "systemd": "systemctl is-active polymarket-arb.service 2>/dev/null; systemctl --no-pager status polymarket-arb.service 2>/dev/null | head -n 20",
        "process": "pgrep -af 'python.*main.py' || true",
        "log_tail": "journalctl -u polymarket-arb.service -n 30 --no-pager 2>/dev/null || true",
        "trade_log": py_db,
        "v_daily_pnl": py_db,
        "arb_signals": (
            "journalctl -u polymarket-arb.service --since '6 hours ago' --no-pager 2>/dev/null "
            "| grep -iE 'spe_|arbitrage|signal|profit|DRY_RUN' | tail -n 25 || true"
        ),
    }

    print(f"=== monitor_status {datetime.now(timezone.utc).isoformat()} ===")
    for name, cmd in checks.items():
        print(f"\n--- {name} ---")
        print(ssh_run(args.host, args.user, args.password, cmd).strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

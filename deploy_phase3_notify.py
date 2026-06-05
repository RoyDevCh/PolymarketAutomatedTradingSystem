#!/usr/bin/env python3
"""Deploy Phase 3 pass notification to remote server."""
import os
from __future__ import annotations

import paramiko
from pathlib import Path

HOST = "192.168.3.117"
USER = "roy"
PASSWORD = os.getenv("REMOTE_PASSWORD", "changeme")
REMOTE = "/home/roy/polymarket-arb"

FILES = [
    "core/phase3_evaluator.py",
    "core/phase3_notify.py",
    "core/telegram_notify.py",
    "core/config.py",
    "main.py",
    ".env.example",
]

ENV_LINES = [
    "PHASE3_NOTIFY_ENABLED=true",
    "PHASE3_MIN_UPTIME_HOURS=48",
    "PHASE3_MIN_ATTEMPTS=100",
    "PHASE3_MAX_LEG_RISK_RATE=0.05",
    "PHASE3_MIN_SLIPPAGE_PASS_RATE=0.90",
    "PHASE3_CHECK_INTERVAL_SECONDS=3600",
    "PHASE3_GHOST_GRACE_SECONDS=1800",
]


def main() -> int:
    root = Path(__file__).resolve().parent
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=20)
    sftp = ssh.open_sftp()

    for rel in FILES:
        local = root / rel
        remote = f"{REMOTE}/{rel}"
        sftp.put(str(local), remote)
        print(f"uploaded {rel}")

    sftp.close()

    for line in ENV_LINES:
        key = line.split("=", 1)[0]
        ssh.exec_command(
            f"grep -q '^{key}=' {REMOTE}/.env 2>/dev/null || echo '{line}' >> {REMOTE}/.env"
        )

    restart_cmd = (
        f"echo '{PASSWORD}' | sudo -S systemctl restart polymarket-arb.service 2>/dev/null; "
        "sleep 2; systemctl is-active polymarket-arb.service"
    )
    _, stdout, stderr = ssh.exec_command(restart_cmd, timeout=30)
    status = (stdout.read() + stderr.read()).decode().strip()
    print(f"service status: {status}")

    sftp = ssh.open_sftp()
    sftp.put(str(root / "test_phase3_evaluator.py"), f"{REMOTE}/test_phase3_evaluator.py")
    sftp.close()

    _, stdout, _ = ssh.exec_command(
        f"journalctl -u polymarket-arb.service -n 15 --no-pager | grep -iE 'phase3|heartbeat|INIT' || true"
    )
    print(stdout.read().decode("utf-8", errors="replace"))

    ssh.close()
    print("deploy complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

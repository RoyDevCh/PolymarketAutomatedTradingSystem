#!/usr/bin/env python3
"""Deploy spread scanner + DRY_RUN support to remote."""
from __future__ import annotations

import os
import time
from pathlib import Path

import paramiko

HOST = os.getenv("REMOTE_HOST", "192.168.3.117")
USER = os.getenv("REMOTE_USER", "roy")
PASSWORD = os.getenv("REMOTE_PASSWORD", "changeme")
REMOTE = "/home/roy/polymarket-arb"
LOCAL = Path(__file__).resolve().parent

FILES = [
    "core/config.py",
    "core/oeg.py",
    "core/spe.py",
    "core/spread_scanner.py",
    "poke_spe.py",
    ".env.example",
]


def main() -> None:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=15)
    sftp = ssh.open_sftp()

    for rel in FILES:
        local = LOCAL / rel
        remote = f"{REMOTE}/{rel}"
        sftp.put(str(local), remote)
        print(f"  uploaded {rel}")
    sftp.close()

    # Add DRY_RUN=false to .env if not present
    ssh.exec_command(f"grep -q '^DRY_RUN=' {REMOTE}/.env || echo 'DRY_RUN=false' >> {REMOTE}/.env")

    # Restart service
    ssh.exec_command(f"echo {PASSWORD} | sudo -S systemctl restart polymarket-arb.service 2>/dev/null")
    time.sleep(5)

    _, stdout, _ = ssh.exec_command("systemctl is-active polymarket-arb.service")
    print(f"\n  service: {stdout.read().decode().strip()}")

    # Run spread scanner (2-minute timeout)
    print("\n  Running spread_scanner (this takes ~1 min)...")
    _, stdout, stderr = ssh.exec_command(
        f"cd {REMOTE} && source venv/bin/activate && source ~/.proxyrc && "
        "timeout 120 python3 -m core.spread_scanner --top 15 2>&1",
        timeout=180,
    )
    print(stdout.read().decode("utf-8", errors="replace"))
    err = stderr.read().decode("utf-8", errors="replace")
    if err:
        print("STDERR:", err[:500])

    ssh.close()


if __name__ == "__main__":
    main()
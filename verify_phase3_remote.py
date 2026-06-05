#!/usr/bin/env python3
import os
from __future__ import annotations

import paramiko

HOST = "192.168.3.117"
USER = "roy"
PASSWORD = os.getenv("REMOTE_PASSWORD", "changeme")
REMOTE = "/home/roy/polymarket-arb"


def main() -> int:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=20)

    checks = [
        "systemctl is-active polymarket-arb.service",
        "journalctl -u polymarket-arb.service -n 50 --no-pager | grep -i phase3 || true",
        "grep PHASE3 /home/roy/polymarket-arb/.env || true",
        f"cd {REMOTE} && source venv/bin/activate && python3 test_phase3_evaluator.py 2>&1 || true",
    ]
    for cmd in checks:
        print(f"\n--- {cmd[:70]} ---")
        _, stdout, stderr = ssh.exec_command(cmd, timeout=60)
        print((stdout.read() + stderr.read()).decode("utf-8", errors="replace")[:1200])

    sftp = ssh.open_sftp()
    sftp.put(
        str(__file__).replace("verify_phase3_remote.py", "test_phase3_evaluator.py"),
        f"{REMOTE}/test_phase3_evaluator.py",
    )
    sftp.close()

    _, stdout, _ = ssh.exec_command(
        f"cd {REMOTE} && source venv/bin/activate && python3 test_phase3_evaluator.py 2>&1",
        timeout=60,
    )
    print("\n--- evaluator ---")
    print(stdout.read().decode("utf-8", errors="replace"))

    ssh.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

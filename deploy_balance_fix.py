"""Deploy CLOB balance heartbeat fix to remote server."""
import os
from __future__ import annotations

import time
from pathlib import Path

import paramiko

HOST = "192.168.3.117"
USER = "roy"
PASSWORD = os.getenv("REMOTE_PASSWORD", "changeme")
REMOTE = "/home/roy/polymarket-arb"
LOCAL = Path(__file__).resolve().parent

FILES = [
    "core/clob_client.py",
    "main.py",
]


def main() -> None:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=15)
    sftp = ssh.open_sftp()
    for rel in FILES:
        local = LOCAL / rel
        remote = f"{REMOTE}/{rel.replace(chr(92), '/')}"
        sftp.put(str(local), remote)
        print(f"uploaded {rel}")
    sftp.close()

    ssh.exec_command(f"echo {PASSWORD} | sudo -S systemctl restart polymarket-arb.service")
    time.sleep(8)

    _, stdout, _ = ssh.exec_command(
        f"cd {REMOTE} && source venv/bin/activate && source ~/.proxyrc && "
        "python3 -c \""
        "from core.clob_client import get_collateral_balance_usd; "
        "b=get_collateral_balance_usd(); "
        "print(f'balance_usd={b}')"
        "\" 2>&1"
    )
    print("balance check:", stdout.read().decode("utf-8", errors="replace").strip())

    _, stdout, _ = ssh.exec_command(
        "journalctl -u polymarket-arb.service -n 25 --no-pager | grep -iE 'Telegram|balance|heartbeat|error' || true"
    )
    print(stdout.read().decode("utf-8", errors="replace"))
    ssh.close()


if __name__ == "__main__":
    main()

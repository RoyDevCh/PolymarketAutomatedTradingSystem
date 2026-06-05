#!/usr/bin/env python3
"""Deploy Phase 4 to remote host (systemd + file upload)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

HOST = "192.168.3.117"
USER = "roy"
PASS = os.getenv("REMOTE_PASSWORD", "changeme")
REMOTE = "/home/roy/polymarket-arb"
LOCAL = Path(__file__).resolve().parent

UPLOAD = [
    "core/config.py",
    "core/telegram_notify.py",
    "core/heartbeat.py",
    "core/rmc.py",
    "main.py",
    "deploy/polymarket-arb.service",
    "deploy/install_systemd.sh",
    "monitor_status.py",
]

ENV_KEYS = {
    "TELEGRAM_ENABLED": "false",
    "HEARTBEAT_INTERVAL_SECONDS": "3600",
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_CHAT_ID": "",
}


def sftp_put(sftp, local: Path, remote: str) -> None:
    parent = os.path.dirname(remote)
    parts: list[str] = []
    p = parent
    while p and p != "/":
        parts.append(p)
        p = os.path.dirname(p)
    for d in reversed(parts):
        try:
            sftp.stat(d)
        except OSError:
            sftp.mkdir(d)
    with sftp.file(remote, "w") as rf:
        rf.write(local.read_text(encoding="utf-8"))


def merge_env(sftp, remote_env: str) -> list[str]:
    try:
        with sftp.open(remote_env, "r") as f:
            existing = f.read().decode("utf-8", errors="replace")
    except OSError:
        existing = ""
    present = set()
    for line in existing.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            present.add(line.split("=", 1)[0].strip())
    added = []
    for k, v in ENV_KEYS.items():
        if k not in present:
            added.append(f"{k}={v}")
    if not added:
        return []
    block = "\n# Phase 4 Telegram placeholders\n" + "\n".join(added) + "\n"
    mode = "a" if existing else "w"
    with sftp.open(remote_env, mode) as f:
        f.write(block.encode("utf-8"))
    return added


def run(ssh, cmd: str, timeout: int = 300) -> str:
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return f"exit={code}\n{out}{err}".strip()


def main() -> int:
    report: list[str] = []
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASS, timeout=25)
    sftp = ssh.open_sftp()

    for rel in UPLOAD:
        local = LOCAL / rel
        if not local.exists():
            report.append(f"SKIP missing {rel}")
            continue
        remote = f"{REMOTE}/{rel}"
        sftp_put(sftp, local, remote)
        report.append(f"UPLOAD {rel}")

    added = merge_env(sftp, f"{REMOTE}/.env")
    report.append(f"ENV added: {added or 'none'}")

    sftp.close()

    report.append("STOP\n" + run(ssh, "pkill -f 'python.*main.py' 2>/dev/null || true; sleep 2; pgrep -af 'python.*main.py' || echo stopped"))
    report.append(
        "SYSTEMD\n"
        + run(
            ssh,
            f"echo {PASS!r} | sudo -S cp {REMOTE}/deploy/polymarket-arb.service /etc/systemd/system/polymarket-arb.service && echo {PASS!r} | sudo -S systemctl daemon-reload && echo {PASS!r} | sudo -S systemctl enable polymarket-arb.service && echo {PASS!r} | sudo -S systemctl restart polymarket-arb.service",
            timeout=120,
        )
    )
    report.append("STATUS\n" + run(ssh, "systemctl is-active polymarket-arb.service; systemctl --no-pager -l status polymarket-arb.service | head -n 35"))
    report.append(
        "LOGS\n"
        + run(
            ssh,
            f"tail -n 60 {REMOTE}/logs/main_debug.log 2>/dev/null; "
            f"tail -n 60 {REMOTE}/logs/*.log 2>/dev/null | tail -n 60; "
            "journalctl -u polymarket-arb.service -n 40 --no-pager 2>/dev/null || true",
        )
    )
    report.append(
        "ARB_GREP\n"
        + run(
            ssh,
            f"grep -h -iE 'arbitrage|arb_opp|opportunity|ARBITRAGE' {REMOTE}/logs/*.log 2>/dev/null | tail -n 100 || true",
        )
    )

    ssh.close()
    text = "\n".join(report)
    (LOCAL / "phase4_deploy_log.txt").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Configure Telegram on remote server and send test heartbeat."""
import os
from __future__ import annotations

import argparse
import json
import re
import sys
import time

import paramiko

HOST = "192.168.3.117"
USER = "roy"
PASSWORD = os.getenv("REMOTE_PASSWORD", "changeme")
REMOTE_DIR = "/home/roy/polymarket-arb"
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
BOT_USERNAME = "tradeformy_bot"


def ssh_run(ssh: paramiko.SSHClient, cmd: str, timeout: int = 30) -> str:
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return stdout.read().decode("utf-8", errors="replace")


def update_env(content: str, key: str, value: str) -> str:
    pattern = rf"^{re.escape(key)}=.*$"
    line = f"{key}={value}"
    if re.search(pattern, content, flags=re.MULTILINE):
        return re.sub(pattern, line, content, flags=re.MULTILINE)
    return content.rstrip() + "\n" + line + "\n"


def discover_chat_id(ssh: paramiko.SSHClient, poll_seconds: int = 0) -> str:
    if poll_seconds <= 0:
        raw = ssh_run(
            ssh,
            f"source ~/.proxyrc 2>/dev/null; curl -s https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
        )
        updates = [raw]
    else:
        updates = []
        deadline = time.time() + poll_seconds
        while time.time() < deadline:
            raw = ssh_run(
                ssh,
                f"source ~/.proxyrc 2>/dev/null; curl -s https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
            )
            updates.append(raw)
            remaining = int(deadline - time.time())
            print(f"Waiting for message to @{BOT_USERNAME} ... {remaining}s left")
            time.sleep(5)

    for raw in updates:
        try:
            data = json.loads(raw)
            for item in data.get("result", []):
                msg = item.get("message") or item.get("edited_message") or {}
                chat = msg.get("chat") or {}
                if "id" in chat:
                    return str(chat["id"])
        except json.JSONDecodeError:
            pass
    return ""


def deploy_heartbeat_fix(ssh: paramiko.SSHClient) -> None:
    local = __file__.replace("setup_telegram.py", "core/heartbeat.py")
    try:
        with open(local, "rb") as f:
            data = f.read()
        sftp = ssh.open_sftp()
        sftp.putfo(__import__("io").BytesIO(data), f"{REMOTE_DIR}/core/heartbeat.py")
        sftp.close()
        print("Deployed core/heartbeat.py (startup heartbeat)")
    except OSError as e:
        print(f"Skip heartbeat deploy: {e}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chat-id", help="Telegram chat id (numeric)")
    parser.add_argument("--poll", type=int, default=0, help="Seconds to poll getUpdates")
    args = parser.parse_args()

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=10)

    deploy_heartbeat_fix(ssh)

    env_path = f"{REMOTE_DIR}/.env"
    content = ssh_run(ssh, f"cat {env_path}")

    content = update_env(content, "TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    content = update_env(content, "TELEGRAM_ENABLED", "true")
    content = update_env(content, "HEARTBEAT_INTERVAL_SECONDS", "3600")

    chat_id = (args.chat_id or "").strip()
    if not chat_id:
        m = re.search(r"^TELEGRAM_CHAT_ID=(.*)$", content, flags=re.MULTILINE)
        if m:
            chat_id = m.group(1).strip()
    if not chat_id:
        print(f"Send any message to @{BOT_USERNAME} on Telegram")
        chat_id = discover_chat_id(ssh, poll_seconds=args.poll)

    if not chat_id:
        print("No chat_id found. Rerun: python setup_telegram.py --chat-id YOUR_ID")
        sys.exit(1)

    content = update_env(content, "TELEGRAM_CHAT_ID", chat_id)
    print(f"Using chat_id={chat_id}")

    sftp = ssh.open_sftp()
    with sftp.open(env_path, "w") as f:
        f.write(content.encode())
    sftp.close()
    print("Updated remote .env")

    test_msg = "Polymarket Arb: Telegram configured. Hourly heartbeat active."
    send_raw = ssh_run(
        ssh,
        (
            "source ~/.proxyrc 2>/dev/null; "
            f"curl -s -X POST https://api.telegram.org/bot{BOT_TOKEN}/sendMessage "
            f"-H 'Content-Type: application/json' "
            f"-d '{{\"chat_id\":\"{chat_id}\",\"text\":\"{test_msg}\"}}'"
        ),
    )
    print("sendMessage:", send_raw[:500])

    print("Restarting polymarket-arb.service...")
    ssh_run(ssh, f"echo {PASSWORD} | sudo -S systemctl restart polymarket-arb.service")
    time.sleep(4)
    print("service status:", ssh_run(ssh, "systemctl is-active polymarket-arb.service").strip())
    print(ssh_run(ssh, "journalctl -u polymarket-arb.service -n 15 --no-pager | grep -i telegram || true"))
    ssh.close()


if __name__ == "__main__":
    main()

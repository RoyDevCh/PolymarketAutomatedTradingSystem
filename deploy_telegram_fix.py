"""Deploy telegram proxy fix and restart service."""
import os
import paramiko
import time
from pathlib import Path

HOST = "192.168.3.117"
USER = "roy"
PASSWORD = os.getenv("REMOTE_PASSWORD", "changeme")
LOCAL = Path(__file__).parent / "core" / "telegram_notify.py"
REMOTE = "/home/roy/polymarket-arb/core/telegram_notify.py"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASSWORD, timeout=10)
sftp = ssh.open_sftp()
sftp.put(str(LOCAL), REMOTE)
sftp.close()
ssh.exec_command(f"echo {PASSWORD} | sudo -S systemctl restart polymarket-arb.service")
time.sleep(5)
_, stdout, _ = ssh.exec_command("journalctl -u polymarket-arb.service -n 20 --no-pager | grep -i telegram")
print(stdout.read().decode("utf-8", errors="replace"))
ssh.close()

"""Deploy Phase 3 updates to remote server and run canary test."""
import paramiko
import time
import os

LOCAL_DIR = "polymarket-arb"
REMOTE_DIR = "/home/roy/polymarket-arb"

FILES = [
    "core/clob_client.py",
    "core/config.py",
    "core/oeg.py",
    "requirements.txt",
    "test_phase3_canary.py",
]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.3.117", username="roy", password="kaiyic", timeout=10)

ssh.exec_command(
    'curl -s -X PUT http://127.0.0.1:9090/proxies/Polymarket '
    '-H "Content-Type:application/json" -d \'{"name": "JP-01"}\''
)
time.sleep(2)

sftp = ssh.open_sftp()
for f in FILES:
    local = os.path.join(LOCAL_DIR, f)
    remote = f"{REMOTE_DIR}/{f}"
    sftp.put(local, remote)
    print(f"Uploaded: {f}")
sftp.close()

cmd = (
    f"cd {REMOTE_DIR} && source venv/bin/activate && source ~/.proxyrc && "
    f"timeout 90 python3 test_phase3_canary.py 2>&1"
)
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=100)
out = stdout.read().decode("utf-8", errors="replace")
for line in out.split("\n"):
    if line.strip():
        print(line.encode("ascii", "replace").decode("ascii")[:250])

ssh.close()

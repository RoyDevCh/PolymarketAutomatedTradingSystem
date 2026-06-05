"""Upload and run a script on remote server."""
import sys
import paramiko
import time

SCRIPT = sys.argv[1] if len(sys.argv) > 1 else "test_metamask_v8.py"
LOCAL = f"polymarket-arb/{SCRIPT}"
REMOTE = f"/home/roy/polymarket-arb/{SCRIPT}"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.3.117", username="roy", password="kaiyic", timeout=10)

ssh.exec_command(
    'curl -s -X PUT http://127.0.0.1:9090/proxies/Polymarket '
    '-H "Content-Type:application/json" -d \'{"name": "JP-01"}\''
)
time.sleep(2)

sftp = ssh.open_sftp()
sftp.put(LOCAL, REMOTE)
sftp.close()

cmd = f"cd /home/roy/polymarket-arb && source venv/bin/activate && source ~/.proxyrc && timeout 90 python3 {SCRIPT} 2>&1"
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=100)
out = stdout.read().decode("utf-8", errors="replace")
for line in out.split("\n"):
    if line.strip():
        safe = line.encode("ascii", "replace").decode("ascii")
        print(safe[:250])

ssh.close()

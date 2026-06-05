import paramiko
import re
from pathlib import Path

HOST, USER, PASS = "192.168.3.117", "roy", "kaiyic"
REMOTE = "/home/roy/polymarket-arb"
LOCAL = Path(__file__).resolve().parent / "test_probe_trade.py"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=25)
sftp = ssh.open_sftp()
sftp.put(str(LOCAL), f"{REMOTE}/test_probe_trade.py")
sftp.close()
cmd = (
    f"bash -lc 'cd {REMOTE} && source ~/.proxyrc 2>/dev/null && "
    f"source venv/bin/activate && python test_probe_trade.py'"
)
_, o, e = ssh.exec_command(cmd, timeout=300)
code = o.channel.recv_exit_status()
out = re.sub(r"[^\x00-\x7F]+", "?", (o.read() + e.read()).decode(errors="replace"))
Path(__file__).resolve().parent.joinpath("probe_run_out.txt").write_text(
    f"exit={code}\n{out}", encoding="utf-8"
)
print(out)
print("exit", code)
ssh.close()

"""Check current balance and config on remote server."""
import os

import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(os.getenv("REMOTE_HOST", "192.168.3.117"), username=os.getenv("REMOTE_USER", "roy"), password=os.getenv("REMOTE_PASSWORD", "changeme"), timeout=10)

sftp = ssh.open_sftp()
sftp.put("check_clob_balance.py", "/home/roy/polymarket-arb/check_clob_balance.py")
sftp.close()

cmds = [
    'grep -E "MAX_TRADE_SIZE|MIN_PROFIT|GAMMA_MIN|DEPOSIT_WALLET|WALLET_ADDRESS" /home/roy/polymarket-arb/.env',
    "cd /home/roy/polymarket-arb && source venv/bin/activate && source ~/.proxyrc && python3 check_clob_balance.py 2>&1",
    'cd /home/roy/polymarket-arb && source venv/bin/activate && python3 -c "import sqlite3; db=sqlite3.connect(\'db/arbitrage.db\'); r=db.execute(\'SELECT COUNT(*), COALESCE(SUM(realized_profit),0) FROM trade_log\').fetchone(); print(f\'TRADES={r[0]} PNL={r[1]:.4f}\')" 2>&1',
]

for c in cmds:
    stdin, stdout, stderr = ssh.exec_command(c, timeout=30)
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    if out:
        print(out)
    if err:
        print("ERR:", err[:300])

ssh.close()

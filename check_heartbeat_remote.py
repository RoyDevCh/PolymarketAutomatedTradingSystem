#!/usr/bin/env python3
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(os.getenv("REMOTE_HOST", "192.168.3.117"), username=os.getenv("REMOTE_USER", "roy"), password=os.getenv("REMOTE_PASSWORD", "changeme"), timeout=20)

cmds = [
    "systemctl is-active polymarket-arb.service",
    "systemctl show polymarket-arb.service -p ActiveEnterTimestamp --value",
    "journalctl -u polymarket-arb.service -n 20 --no-pager | grep -iE 'heartbeat|balance|error|INIT|phase3|fill_tracker'",
    "cd /home/roy/polymarket-arb && source venv/bin/activate && python3 -c \"import sqlite3; c=sqlite3.connect('db/arbitrage.db'); print('trade_log', c.execute('SELECT COUNT(*) FROM trade_log').fetchone()[0])\"",
]
for cmd in cmds:
    print(f"\n--- {cmd[:70]} ---")
    _, o, e = ssh.exec_command(cmd, timeout=30)
    print((o.read() + e.read()).decode("utf-8", errors="replace")[:1200])
ssh.close()

"""Quick remote status check."""
import os

import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(os.getenv("REMOTE_HOST", "192.168.3.117"), username=os.getenv("REMOTE_USER", "roy"), password=os.getenv("REMOTE_PASSWORD", "changeme"), timeout=10)

cmds = [
    ("service", "systemctl is-active polymarket-arb.service"),
    ("started", "systemctl show polymarket-arb.service -p ActiveEnterTimestamp --value"),
    ("process", "pgrep -af 'python.*main.py' || true"),
    ("env", "grep -E 'GAMMA_MIN|MIN_PROFIT|MAX_TRADE|TELEGRAM' /home/roy/polymarket-arb/.env"),
    ("trades", "sqlite3 /home/roy/polymarket-arb/db/arbitrage.db 'SELECT COUNT(*), COALESCE(SUM(realized_profit),0) FROM trade_log;'"),
    ("daily", "sqlite3 /home/roy/polymarket-arb/db/arbitrage.db 'SELECT * FROM v_daily_pnl LIMIT 3;'"),
    ("signals_6h", "journalctl -u polymarket-arb.service --since '6 hours ago' --no-pager | grep -ciE 'spe_|arbitrage|oeg_signal' || true"),
    ("leg_risk", "journalctl -u polymarket-arb.service --since '6 hours ago' --no-pager | grep -ci LEG_RISK || true"),
    ("telegram", "journalctl -u polymarket-arb.service --since '2 hours ago' --no-pager | grep -i telegram | tail -3"),
    ("errors", "journalctl -u polymarket-arb.service --since '6 hours ago' --no-pager | grep -iE 'error|exception|traceback' | tail -5"),
]
for name, cmd in cmds:
    _, stdout, stderr = ssh.exec_command(cmd, timeout=25)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    print(f"[{name}] {out or err or '(empty)'}")

ssh.close()

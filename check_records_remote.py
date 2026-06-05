"""Query remote trade_log and recent arb logs."""
from __future__ import annotations

import os

import paramiko

HOST = os.getenv("REMOTE_HOST", "192.168.3.117")
USER = os.getenv("REMOTE_USER", "roy")
PASSWORD = os.getenv("REMOTE_PASSWORD", "changeme")
REMOTE = "/home/roy/polymarket-arb"

QUERY_SCRIPT = """import sqlite3
db = sqlite3.connect('db/arbitrage.db')
db.row_factory = sqlite3.Row
n = db.execute('SELECT COUNT(*) FROM trade_log').fetchone()[0]
print('trade_log_count', n)
rows = db.execute(
    "SELECT id, datetime(timestamp, 'unixepoch') as ts, signal_id, market_question, "
    "yes_status, no_status, yes_fill_price, no_fill_price, realized_profit, has_leg_risk "
    "FROM trade_log ORDER BY id DESC LIMIT 10"
).fetchall()
for r in rows:
    q = (r['market_question'] or '')[:55]
    print(
        f"  #{r['id']} {r['ts']} | {r['yes_status']}/{r['no_status']} | "
        f"fill {r['yes_fill_price']}/{r['no_fill_price']} | pnl {r['realized_profit']} | "
        f"leg={r['has_leg_risk']} | {q}"
    )
try:
    pnl = db.execute('SELECT * FROM v_daily_pnl').fetchall()
    print('v_daily_pnl', pnl)
except Exception as e:
    print('v_daily_pnl_err', e)
cb = db.execute('SELECT COUNT(*) FROM circuit_breaker_log').fetchone()[0]
print('circuit_breaker_events', cb)
sig = db.execute('SELECT COUNT(*) FROM signal_stats').fetchone()[0]
print('signal_stats_rows', sig)
"""


def run(ssh: paramiko.SSHClient, cmd: str, timeout: int = 40) -> str:
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return (stdout.read() + stderr.read()).decode("utf-8", errors="replace")


def main() -> None:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=15)

    sftp = ssh.open_sftp()
    remote_script = f"{REMOTE}/check_records_tmp.py"
    with sftp.file(remote_script, "w") as f:
        f.write(QUERY_SCRIPT)
    sftp.close()

    print("=== service ===")
    print(run(ssh, "systemctl is-active polymarket-arb.service").strip())

    print("\n=== sqlite trade_log ===")
    print(run(ssh, f"cd {REMOTE} && source venv/bin/activate && python3 check_records_tmp.py").strip())

    print("\n=== recent arb/signal logs (12h) ===")
    log_cmd = (
        'journalctl -u polymarket-arb.service --since "12 hours ago" --no-pager 2>/dev/null '
        '| grep -iE "DRY_RUN_SIGNAL|spe_|arbitrage|oeg_signal|TRADE_CONFIRMED|probe|leg_risk|rmc_trade" '
        '| tail -n 20 || true'
    )
    out = run(ssh, log_cmd).strip()
    print(out if out else "(no matching log lines)")

    ssh.close()


if __name__ == "__main__":
    main()

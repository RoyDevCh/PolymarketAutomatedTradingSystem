#!/usr/bin/env python3
"""Quick status check for microservices"""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.3.117', username='roy', password='kaiyic', timeout=20)

def run(cmd, t=10):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=t)
    stdout.channel.settimeout(t)
    try: return stdout.read().decode('utf-8','replace')
    except: return ''

# Message bus
print('=== Message Bus ===')
print(run('cd /home/roy/polymarket-arb && source venv/bin/activate && python3 -c "from core.message_bus import MessageBus; bus = MessageBus(); print(bus.queue_depth())" 2>&1').strip())

# Service locks
print('\n=== Service Locks ===')
print(run('''cd /home/roy/polymarket-arb && source venv/bin/activate && python3 -c "from core.message_bus import MessageBus; import sqlite3; conn=sqlite3.connect('db/arbitrage.db'); rows=conn.execute('SELECT service_name, pid, heartbeat_at FROM service_lock').fetchall(); [print(f'  {r[0]:5s} pid={r[1]} hb={r[2]:.0f}') for r in rows]; conn.close()" 2>&1''').strip())

# Service status
print('\n=== Service Status ===')
print(f'  monolithic: {run("systemctl is-active polymarket-arb").strip()}')
for svc in ['mdg', 'spe', 'oeg', 'rmc']:
    s = run(f'systemctl is-active polymarket-{svc}').strip()
    print(f'  {svc}: {s}')

# Activity
print('\n=== Recent Activity ===')
for svc in ['mdg', 'spe', 'oeg', 'rmc']:
    out = run(f'journalctl -u polymarket-{svc} --no-pager -n 3 2>&1')
    lines = [l for l in out.splitlines() if 'INFO' in l or 'ERROR' in l or 'python' in l.lower()]
    if lines:
        print(f'  [{svc.upper()}] {lines[-1][-150:]}')
    else:
        print(f'  [{svc.upper()}] (no recent activity)')

ssh.close()
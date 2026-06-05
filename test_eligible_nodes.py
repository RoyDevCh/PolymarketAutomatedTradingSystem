#!/usr/bin/env python3
"""Test each Polymarket-eligible node for geoblock and order API access."""
import paramiko, json, time

SSH_HOST = '192.168.3.117'
SSH_USER = 'roy'
SSH_PASS = 'kaiyic'

NODES_TO_TEST = [
    '🇯🇵 日本01',
    '🇯🇵 日本02',
    '🇯🇵 日本03',
    '🇯🇵 日本04',
    '🇭🇰 香港01',
    '🇭🇰 香港02',
    '🇭🇰 香港03',
    '🇭🇰 香港04',
    '🇨🇦 加拿大01',
    '🇰🇷 韩国01',
    '🇰🇷 韩国02',
    '🇮🇩 印尼01',
    '🇹🇷 土耳其01',
]

def run(ssh, cmd, t=15):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=t)
    stdout.channel.settimeout(t)
    try:
        return stdout.read().decode('utf-8', 'replace')
    except:
        return ''

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(SSH_HOST, username=SSH_USER, password=SSH_PASS, timeout=20)

    print(f"{'Node':28s} | {'IP':15s} | {'Country':7s} | {'Region':6s} | {'Blocked':7s} | Order API")
    print("-" * 110)

    for node in NODES_TO_TEST:
        # Switch Polymarket group to this node
        switch_cmd = f"""curl -s -X PUT http://127.0.0.1:9090/proxies/Polymarket -H 'Content-Type: application/json' -d '{{"name": "{node}"}}' 2>&1"""
        run(ssh, switch_cmd)
        time.sleep(3)

        # Test geoblock
        geo = run(ssh, 'curl -s -x http://127.0.0.1:7890 https://polymarket.com/api/geoblock 2>&1')
        try:
            d = json.loads(geo)
            country = d.get('country', '?')
            region = d.get('region', '')
            blocked = d.get('blocked', '?')
        except:
            country = region = '?'
            blocked = 'parse_err'

        # Test order API
        order = run(ssh, """curl -s -x http://127.0.0.1:7890 -X POST https://clob.polymarket.com/order -H "Content-Type: application/json" -d '{}' 2>&1""")
        try:
            od = json.loads(order)
            err = od.get('error', '')
            if 'region' in err:
                api_result = '403 BLOCKED'
            elif 'Unauthorized' in err:
                api_result = 'OK (auth)'
            else:
                api_result = err[:35]
        except:
            if '403' in order:
                api_result = '403 BLOCKED'
            else:
                api_result = order.strip()[:35]

        # Get exit IP
        ip_info = run(ssh, 'curl -s -x http://127.0.0.1:7890 https://httpbin.org/ip 2>&1')
        try:
            ip_d = json.loads(ip_info)
            ip = ip_d.get('origin', '?')
        except:
            ip = ip_info.strip()[:20]

        print(f"{node:28s} | {ip:15s} | {country:7s} | {region:6s} | {str(blocked):7s} | {api_result}")

    # Switch back to JP01
    run(ssh, """curl -s -X PUT http://127.0.0.1:9090/proxies/Polymarket -H 'Content-Type: application/json' -d '{"name": "🇯🇵 日本01"}' 2>&1""")
    time.sleep(2)
    print("\nSwitched back to 🇯🇵 日本01")
    ssh.close()

if __name__ == '__main__':
    main()
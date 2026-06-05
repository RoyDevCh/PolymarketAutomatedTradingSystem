#!/usr/bin/env python3
"""Remove blocked nodes (ID/SG) from Polymarket group, keep only verified-eligible nodes.
Verified eligible: JP (API OK), HK (blocked=false), CA (blocked=false), TR (blocked=false), KR (TBD but likely OK)
Verified blocked: ID (SG exit, 403), SG (explicit), TW (close-only), TH (close-only)
"""
import paramiko, os, time, yaml, json

SSH_HOST = '192.168.3.117'
SSH_USER = 'roy'
SSH_PASS = os.getenv('REMOTE_PASSWORD', 'kaiyic')

# Only include nodes verified NOT blocked by Polymarket
POLYMARKET_ELIGIBLE = [
    # JP - Frontend UI restricted only, API works
    '🇯🇵 日本01', '🇯🇵 日本02', '🇯🇵 日本03', '🇯🇵 日本04',
    '🇯🇵 日本01 电信优化', '🇯🇵 日本02 电信优化',
    '🇯🇵 日本01 CloudFront', '🇯🇵 日本02 CloudFront',
    # HK - blocked=false, confirmed OK
    '🇭🇰 香港01', '🇭🇰 香港02', '🇭🇰 香港03', '🇭🇰 香港04',
    # CA - blocked=false, confirmed OK
    '🇨🇦 加拿大01', '🇨🇦 加拿大01 CloudFront',
    # KR - not in blocked list, likely OK
    '🇰🇷 韩国01', '🇰🇷 韩国02',
    # TR - blocked=false, confirmed OK
    '🇹🇷 土耳其01', '🇹🇷 土耳其02',
]

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(SSH_HOST, username=SSH_USER, password=SSH_PASS, timeout=20)

    def run(cmd, t=15):
        _, stdout, stderr = ssh.exec_command(cmd, timeout=t)
        stdout.channel.settimeout(t)
        return (stdout.read() + stderr.read()).decode('utf-8', 'replace')

    # Backup
    print('=== Backup ===')
    print(run('echo kaiyic | sudo -S cp /etc/mihomo/config.yaml /etc/mihomo/config.yaml.bak.clean 2>&1').strip())

    # Read current config
    config_text = run('echo kaiyic | sudo -S cat /etc/mihomo/config.yaml 2>/dev/null')
    parsed = yaml.safe_load(config_text)

    # Update Polymarket group - remove blocked nodes, keep only eligible
    for i, group in enumerate(parsed.get('proxy-groups', [])):
        if group.get('name') == 'Polymarket':
            old_proxies = group.get('proxies', [])
            new_proxies = [p for p in old_proxies if p in POLYMARKET_ELIGIBLE]
            parsed['proxy-groups'][i]['proxies'] = new_proxies
            print(f'Polymarket group: {len(old_proxies)} -> {len(new_proxies)} nodes')
            print(f'  Removed: {[p for p in old_proxies if p not in POLYMARKET_ELIGIBLE]}')
            print(f'  Kept: {new_proxies}')
            break

    # Write updated config
    new_config = yaml.dump(parsed, default_flow_style=False, allow_unicode=True, sort_keys=False)

    sftp = ssh.open_sftp()
    with sftp.open('/tmp/mihomo_config_clean.yaml', 'w') as f:
        f.write(new_config)
    sftp.close()

    # Validate
    validate = run("python3 -c \"import yaml; d=yaml.safe_load(open('/tmp/mihomo_config_clean.yaml')); pm=[g for g in d['proxy-groups'] if g['name']=='Polymarket'][0]; print('OK: PM group has', len(pm['proxies']), 'nodes:', pm['proxies'])\" 2>&1")
    print(f'\nValidation: {validate.strip()[:300]}')

    # Apply
    print('\n=== Applying config ===')
    print(run('echo kaiyic | sudo -S cp /tmp/mihomo_config_clean.yaml /etc/mihomo/config.yaml 2>&1').strip())
    print(run('echo kaiyic | sudo -S systemctl restart mihomo 2>&1').strip())
    time.sleep(8)

    # Check status
    status = run('echo kaiyic | sudo -S systemctl status mihomo 2>&1 | head -8')
    print(f'mihomo: {status[:300]}')

    if 'active (running)' not in status:
        print('FAILED! Restoring backup...')
        print(run('echo kaiyic | sudo -S cp /etc/mihomo/config.yaml.bak.clean /etc/mihomo/config.yaml 2>&1').strip())
        print(run('echo kaiyic | sudo -S systemctl restart mihomo 2>&1').strip())
        ssh.close()
        return

    time.sleep(5)

    # Verify PM group
    pm_info = run('curl -s http://127.0.0.1:9090/proxies/Polymarket 2>&1')
    try:
        d = json.loads(pm_info)
        print(f'\nPolymarket group: now={d.get("now")}, type={d.get("type")}')
        print(f'  Eligible nodes: {d.get("all", [])}')
    except:
        print(f'\nPolymarket group info: {pm_info[:200]}')

    # Restart trading service
    print('\n=== Restarting trading service ===')
    run('echo kaiyic | sudo -S systemctl restart polymarket-arb 2>&1')
    time.sleep(10)
    svc_status = run('systemctl is-active polymarket-arb')
    print(f'Service: {svc_status.strip()}')

    # Final geoblock test with JP01
    print('\n=== Final geoblock test (JP01) ===')
    # Switch back to JP01
    run('''curl -s -X PUT http://127.0.0.1:9090/proxies/Polymarket -H 'Content-Type: application/json' -d '{"name": "🇯🇵 日本01"}' 2>&1''')
    run('''curl -s -X PUT http://127.0.0.1:9090/proxies/Proxies -H 'Content-Type: application/json' -d '{"name": "🇯🇵 日本01"}' 2>&1''')
    time.sleep(2)
    geo = run('curl -s -x http://127.0.0.1:7890 https://polymarket.com/api/geoblock 2>&1')
    print(f'  {geo.strip()[:200]}')

    order = run('''curl -s -x http://127.0.0.1:7890 -X POST https://clob.polymarket.com/order -H 'Content-Type: application/json' -d '{}' 2>&1''')
    print(f'  Order API: {order.strip()[:200]}')

    ssh.close()
    print('\nDone!')

if __name__ == '__main__':
    main()
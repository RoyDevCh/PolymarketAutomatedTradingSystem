#!/usr/bin/env python3
"""Add Japan nodes and Polymarket group to mihomo config - v4 (YAML-safe)."""
import paramiko, os, time, yaml

SSH_HOST = '192.168.3.117'
SSH_USER = 'roy'
SSH_PASS = os.getenv('REMOTE_PASSWORD', 'kaiyic')

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(SSH_HOST, username=SSH_USER, password=SSH_PASS, timeout=20)
    
    def run(cmd, t=15):
        _, stdout, stderr = ssh.exec_command(cmd, timeout=t)
        stdout.channel.settimeout(t)
        return (stdout.read() + stderr.read()).decode('utf-8','replace')
    
    # Backup
    print('=== Backup ===')
    print(run('echo kaiyic | sudo -S cp /etc/mihomo/config.yaml /etc/mihomo/config.yaml.bak.v4 2>&1').strip())
    
    # Read current config
    config_text = run('echo kaiyic | sudo -S cat /etc/mihomo/config.yaml 2>/dev/null')
    
    # Parse as YAML
    parsed = yaml.safe_load(config_text)
    print(f'Current proxies: {len(parsed.get("proxies", []))}')
    print(f'Current groups: {[g["name"] for g in parsed.get("proxy-groups", [])]}')
    
    # Add JP nodes
    jp_nodes = [
        {
            'name': '\U0001f1ef\U0001f1f5 日本01',
            'type': 'anytls',
            'server': 'aws-nrt.edge.qchwnd.moe',
            'port': 443,
            'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
            'alpn': ['h2', 'http/1.1'],
            'skip-cert-verify': False,
            'udp': True,
            'sni': 'moe233-riolu-ce068da0-f2ca-6b9b-c3cb-7dc079ae6f9e.qchwnd.moe',
        },
        {
            'name': '\U0001f1ef\U0001f1f5 日本02',
            'type': 'anytls',
            'server': 'aws-nrt.edge.qchwnd.moe',
            'port': 443,
            'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
            'alpn': ['h2', 'http/1.1'],
            'skip-cert-verify': False,
            'udp': True,
            'sni': 'moe233-riolu-8efefdb7-1701-a524-d925-844f02d32bf4.qchwnd.moe',
        },
        {
            'name': '\U0001f1ef\U0001f1f5 日本03',
            'type': 'anytls',
            'server': '0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org',
            'port': 443,
            'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
            'alpn': ['h2', 'http/1.1'],
            'skip-cert-verify': False,
            'udp': True,
            'sni': 'moe233-riolu-ce068da0-f2ca-6b9b-c3cb-7dc079ae6f9e.qchwnd.moe',
        },
        {
            'name': '\U0001f1ef\U0001f1f5 日本04',
            'type': 'anytls',
            'server': '0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org',
            'port': 443,
            'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
            'alpn': ['h2', 'http/1.1'],
            'skip-cert-verify': False,
            'udp': True,
            'sni': 'moe233-riolu-8efefdb7-1701-a524-d925-844f02d32bf4.qchwnd.moe',
        },
    ]
    
    existing_names = [p['name'] for p in parsed.get('proxies', [])]
    if '\U0001f1ef\U0001f1f5 日本01' not in existing_names:
        parsed['proxies'].extend(jp_nodes)
        print(f'Added {len(jp_nodes)} JP nodes. Total proxies: {len(parsed["proxies"])}')
    else:
        print('JP nodes already exist')
    
    # Update Proxies group
    for group in parsed.get('proxy-groups', []):
        if group.get('name') == 'Proxies':
            for jn in ['\U0001f1ef\U0001f1f5 日本01', '\U0001f1ef\U0001f1f5 日本02', '\U0001f1ef\U0001f1f5 日本03', '\U0001f1ef\U0001f1f5 日本04']:
                if jn not in group.get('proxies', []):
                    group['proxies'].insert(0, jn)
            print(f'Updated Proxies group (now has {len(group["proxies"])} members)')
        if group.get('name') == 'Taiwan-Fallback':
            for jn in ['\U0001f1ef\U0001f1f5 日本01', '\U0001f1ef\U0001f1f5 日本02', '\U0001f1ef\U0001f1f5 日本03', '\U0001f1ef\U0001f1f5 日本04']:
                if jn not in group.get('proxies', []):
                    group['proxies'].append(jn)
            print(f'Updated Taiwan-Fallback group')
    
    # Add Polymarket proxy group
    pm_group_exists = any(g.get('name') == 'Polymarket' for g in parsed.get('proxy-groups', []))
    if not pm_group_exists:
        parsed['proxy-groups'].insert(0, {
            'name': 'Polymarket',
            'type': 'select',
            'proxies': ['\U0001f1ef\U0001f1f5 日本01', '\U0001f1ef\U0001f1f5 日本02', '\U0001f1ef\U0001f1f5 日本03', '\U0001f1ef\U0001f1f5 日本04', 'Proxies'],
        })
        print('Added Polymarket proxy group')
    
    # Add Polymarket routing rules
    pm_rules = [
        'DOMAIN-SUFFIX,polymarket.com,Polymarket',
        'DOMAIN-SUFFIX,clob.polymarket.com,Polymarket',
        'DOMAIN-SUFFIX,gamma-api.polymarket.com,Polymarket',
    ]
    existing_rules = parsed.get('rules', [])
    existing_rules = [r for r in existing_rules if 'polymarket' not in r.lower()]
    parsed['rules'] = pm_rules + existing_rules
    print(f'Added PM routing rules. Total rules: {len(parsed["rules"])}')
    
    # Dump to YAML
    new_config = yaml.dump(parsed, default_flow_style=False, allow_unicode=True, sort_keys=False)
    
    # Write to remote
    sftp = ssh.open_sftp()
    with sftp.open('/tmp/mihomo_config_jp_v4.yaml', 'w') as f:
        f.write(new_config)
    sftp.close()
    
    # Validate on remote
    print('\n=== Validating config ===')
    validate = run("python3 -c \"import yaml; d=yaml.safe_load(open('/tmp/mihomo_config_jp_v4.yaml')); print('YAML OK'); print('Proxies:', len(d.get('proxies',[]))); print('Groups:', [g['name'] for g in d.get('proxy-groups',[])])\" 2>&1")
    print(f'  {validate.strip()[:300]}')
    
    if 'YAML OK' not in validate:
        print('  YAML validation FAILED! Aborting.')
        return
    
    # Apply
    print('\n=== Applying config ===')
    print(run('echo kaiyic | sudo -S cp /tmp/mihomo_config_jp_v4.yaml /etc/mihomo/config.yaml 2>&1').strip())
    print(run('echo kaiyic | sudo -S systemctl restart mihomo 2>&1').strip())
    time.sleep(5)
    
    # Status
    print('\n=== mihomo status ===')
    status = run('echo kaiyic | sudo -S systemctl status mihomo 2>&1 | head -10')
    print(status)
    
    if 'active (running)' not in status:
        print('\n  FAILED! Checking logs...')
        logs = run('echo kaiyic | sudo -S journalctl -u mihomo --since "30 sec ago" --no-pager 2>&1 | tail -5')
        print(logs)
        print('  Restoring backup...')
        print(run('echo kaiyic | sudo -S cp /etc/mihomo/config.yaml.bak.v4 /etc/mihomo/config.yaml 2>&1').strip())
        print(run('echo kaiyic | sudo -S systemctl restart mihomo 2>&1').strip())
        time.sleep(3)
        print(run('echo kaiyic | sudo -S systemctl status mihomo 2>&1 | head -5'))
        ssh.close()
        return
    
    # Wait for mihomo to initialize
    time.sleep(5)
    
    # Switch proxy groups to JP
    print('\n=== Switching proxy groups ===')
    r1 = run('curl -s -X PUT http://127.0.0.1:9090/proxies/Polymarket -H "Content-Type: application/json" -d \'{"name": "🇯🇵 日本01"}\' 2>&1')
    print(f'  Polymarket -> JP01: {r1[:100]}')
    time.sleep(1)
    r2 = run('curl -s -X PUT http://127.0.0.1:9090/proxies/Proxies -H "Content-Type: application/json" -d \'{"name": "🇯🇵 日本01"}\' 2>&1')
    print(f'  Proxies -> JP01: {r2[:100]}')
    time.sleep(3)
    
    # Verify routing
    print('\n=== Verifying JP routing ===')
    ip = run('curl -s -x http://127.0.0.1:7890 https://httpbin.org/ip 2>&1')
    print(f'  Exit IP: {ip.strip()[:200]}')
    
    geo = run('curl -s -x http://127.0.0.1:7890 https://polymarket.com/api/geoblock 2>&1')
    print(f'  Geoblock: {geo.strip()[:300]}')
    
    order = run('curl -s -x http://127.0.0.1:7890 -X POST https://clob.polymarket.com/order -H "Content-Type: application/json" -d \'{}\' 2>&1')
    print(f'  Order API: {order.strip()[:300]}')
    
    ssh.close()

if __name__ == '__main__':
    main()
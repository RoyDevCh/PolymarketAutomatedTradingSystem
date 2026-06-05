#!/usr/bin/env python3
"""Test all eligible Polymarket nodes and update mihomo config.
Eligible = not in Polymarket blocked list: JP, HK, CA, KR, ID, TR
"""
import paramiko, os, time, yaml, json

SSH_HOST = '192.168.3.117'
SSH_USER = 'roy'
SSH_PASS = os.getenv('REMOTE_PASSWORD', 'kaiyic')

# All eligible nodes from subscription JP, HK, CA, KR, ID, TR
# (excludes: US-blocked, GB-blocked, FR-blocked, DE-blocked, SG-close-only, TH-close-only, TW-close-only)
ELIGIBLE_NODES = [
    # === JP (Frontend UI restricted only, API OK) ===
    {'name': '🇯🇵 日本01', 'type': 'anytls', 'server': 'aws-nrt.edge.qchwnd.moe', 'port': 443,
     'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
     'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True,
     'sni': 'moe233-riolu-ce068da0-f2ca-6b9b-c3cb-7dc079ae6f9e.qchwnd.moe'},
    {'name': '🇯🇵 日本02', 'type': 'anytls', 'server': 'aws-nrt.edge.qchwnd.moe', 'port': 443,
     'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
     'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True,
     'sni': 'moe233-riolu-8efefdb7-1701-a524-d925-844f02d32bf4.qchwnd.moe'},
    {'name': '🇯🇵 日本03', 'type': 'anytls', 'server': '0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org', 'port': 443,
     'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
     'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True,
     'sni': 'moe233-riolu-ce068da0-f2ca-6b9b-c3cb-7dc079ae6f9e.qchwnd.moe'},
    {'name': '🇯🇵 日本04', 'type': 'anytls', 'server': '0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org', 'port': 443,
     'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
     'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True,
     'sni': 'moe233-riolu-8efefdb7-1701-a524-d925-844f02d32bf4.qchwnd.moe'},
    # JP vmess (电信优化)
    {'name': '🇯🇵 日本01 电信优化', 'type': 'vmess', 'server': 'cf-nrt.cdn.qchwnd.moe', 'port': 443,
     'uuid': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64', 'alterId': 0, 'cipher': 'auto', 'udp': True,
     'tls': True, 'servername': 'jpm2.riolui.link',
     'network': 'ws',
     'ws-opts': {'path': '/riolu/4?ed=4096', 'headers': {'Host': 'jpm2.riolui.link'}}},
    {'name': '🇯🇵 日本02 电信优化', 'type': 'vmess', 'server': 'cf-nrt.cdn.qchwnd.moe', 'port': 443,
     'uuid': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64', 'alterId': 0, 'cipher': 'auto', 'udp': True,
     'tls': True, 'servername': 'jpdc1.riolui.link',
     'network': 'ws',
     'ws-opts': {'path': '/riolu/7?ed=4096', 'headers': {'Host': 'jpdc1.riolui.link'}}},
    # JP CloudFront
    {'name': '🇯🇵 日本01 CloudFront', 'type': 'vmess', 'server': 'cfn.cdn.moe233.org', 'port': 443,
     'uuid': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64', 'alterId': 0, 'cipher': 'auto', 'udp': True,
     'tls': True, 'servername': 'd232fuc3xd1vzm.cloudfront.net',
     'network': 'ws',
     'ws-opts': {'path': '/riolu/4?ed=4096', 'headers': {'Host': 'd232fuc3xd1vzm.cloudfront.net'}}},
    {'name': '🇯🇵 日本02 CloudFront', 'type': 'vmess', 'server': 'cfn.cdn.moe233.org', 'port': 443,
     'uuid': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64', 'alterId': 0, 'cipher': 'auto', 'udp': True,
     'tls': True, 'servername': 'd27lumjg91ny89.cloudfront.net',
     'network': 'ws',
     'ws-opts': {'path': '/riolu/7?ed=4096', 'headers': {'Host': 'd27lumjg91ny89.cloudfront.net'}}},
    # === HK (Not in blocked list - can trade freely) ===
    {'name': '🇭🇰 香港01', 'type': 'anytls', 'server': '44c9706d-874e-f8b7-05c0-aaaa04a800c7.relay.moe233.org', 'port': 443,
     'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
     'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True,
     'sni': 'moe233-riolu-fd0fcfe0-b92a-f4b5-fe04-53069f5afc1b.qchwnd.moe'},
    {'name': '🇭🇰 香港02', 'type': 'anytls', 'server': '44c9706d-874e-f8b7-05c0-aaaa04a800c7.relay.moe233.org', 'port': 443,
     'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
     'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True,
     'sni': 'moe233-riolu-61a820a2-ab45-6be7-d0d7-aeed72816683.qchwnd.moe'},
    {'name': '🇭🇰 香港03', 'type': 'anytls', 'server': '0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org', 'port': 443,
     'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
     'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True,
     'sni': 'moe233-riolu-fd0fcfe0-b92a-f4b5-fe04-53069f5afc1b.qchwnd.moe'},
    {'name': '🇭🇰 香港04', 'type': 'anytls', 'server': '0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org', 'port': 443,
     'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
     'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True,
     'sni': 'moe233-riolu-61a820a2-ab45-6be7-d0d7-aeed72816683.qchwnd.moe'},
    # === CA (Canada - not blocked, except Ontario) ===
    {'name': '🇨🇦 加拿大01', 'type': 'anytls', 'server': 'raksmart-sjc.edge.qchwnd.moe', 'port': 443,
     'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
     'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True,
     'sni': 'moe233-riolu-f713d121-6926-6cb4-6542-94db1b827091.qchwnd.moe'},
    {'name': '🇨🇦 加拿大01 CloudFront', 'type': 'vmess', 'server': 'cfn.cdn.moe233.org', 'port': 443,
     'uuid': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64', 'alterId': 0, 'cipher': 'auto', 'udp': True,
     'tls': True, 'servername': 'd2eyeotmscglv5.cloudfront.net',
     'network': 'ws',
     'ws-opts': {'path': '/riolu/5?ed=2048', 'headers': {'Host': 'd2eyeotmscglv5.cloudfront.net'}}},
    # === KR (South Korea - not blocked) ===
    {'name': '🇰🇷 韩国01', 'type': 'anytls', 'server': '0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org', 'port': 443,
     'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
     'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True,
     'sni': 'moe233-riolu-5e3746c6-b3a3-8086-d853-bd323b99bae2.qchwnd.moe'},
    {'name': '🇰🇷 韩国02', 'type': 'anytls', 'server': 'jp.edge.moe233.org', 'port': 443,
     'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
     'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True,
     'sni': 'moe233-riolu-5e3746c6-b3a3-8086-d853-bd323b99bae2.qchwnd.moe'},
    # === ID (Indonesia - not blocked) ===
    {'name': '🇮🇩 印尼01', 'type': 'anytls', 'server': '46594d3d-2d7c-ffa2-2cc7-af4c6c347312.relay.moe233.org', 'port': 443,
     'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
     'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True,
     'sni': 'moe233-riolu-655d3987-e9a4-935a-877e-a91ce6fe776e.qchwnd.moe'},
    {'name': '🇮🇩 印尼02', 'type': 'anytls', 'server': '46594d3d-2d7c-ffa2-2cc7-af4c6c347312.relay.moe233.org', 'port': 443,
     'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
     'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True,
     'sni': 'moe233-riolu-c4c745f3-e49f-e7ac-b9d6-9a0fbe8511f0.qchwnd.moe'},
    # === TR (Turkey - not blocked) ===
    {'name': '🇹🇷 土耳其01', 'type': 'anytls', 'server': '0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org', 'port': 443,
     'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
     'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True,
     'sni': 'moe233-riolu-e8c6cfe7-e044-dca9-8f45-8e52fd32f4de.qchwnd.moe'},
    {'name': '🇹🇷 土耳其02', 'type': 'anytls', 'server': '0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org', 'port': 443,
     'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
     'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True,
     'sni': 'moe233-riolu-e8c6cfe7-e044-dca9-8f45-8e52fd32f4de.qchwnd.moe'},
]

# Polymarket group: url-test for auto-selection with fallback
PM_GROUP_MEMBERS = [n['name'] for n in ELIGIBLE_NODES]


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
    print(run('echo kaiyic | sudo -S cp /etc/mihomo/config.yaml /etc/mihomo/config.yaml.bak.eligible 2>&1').strip())
    
    # Read current config
    config_text = run('echo kaiyic | sudo -S cat /etc/mihomo/config.yaml 2>/dev/null')
    parsed = yaml.safe_load(config_text)
    
    print(f'Current proxies: {len(parsed.get("proxies", []))}')
    print(f'Current groups: {[g["name"] for g in parsed.get("proxy-groups", [])]}')
    
    # Add eligible nodes (skip if already exists)
    existing_names = {p['name'] for p in parsed.get('proxies', [])}
    added = 0
    for node in ELIGIBLE_NODES:
        if node['name'] not in existing_names:
            parsed['proxies'].append(node)
            added += 1
    print(f'Added {added} new eligible proxy nodes. Total: {len(parsed["proxies"])}')
    
    # Update Polymarket group to url-test type with all eligible nodes
    pm_found = False
    for i, group in enumerate(parsed.get('proxy-groups', [])):
        if group.get('name') == 'Polymarket':
            # Replace with url-test for auto-selection
            parsed['proxy-groups'][i] = {
                'name': 'Polymarket',
                'type': 'url-test',
                'proxies': PM_GROUP_MEMBERS,
                'url': 'http://www.gstatic.com/generate_204',
                'interval': 300,  # test every 5 min
                'tolerance': 100,  # 100ms tolerance
            }
            pm_found = True
            print(f'Updated Polymarket group to url-test with {len(PM_GROUP_MEMBERS)} nodes')
            break
    
    if not pm_found:
        # Insert at beginning
        parsed['proxy-groups'].insert(0, {
            'name': 'Polymarket',
            'type': 'url-test',
            'proxies': PM_GROUP_MEMBERS,
            'url': 'http://www.gstatic.com/generate_204',
            'interval': 300,
            'tolerance': 100,
        })
        print(f'Created Polymarket url-test group with {len(PM_GROUP_MEMBERS)} nodes')
    
    # Also add eligible nodes to Proxies group
    for group in parsed.get('proxy-groups', []):
        if group.get('name') == 'Proxies':
            for name in PM_GROUP_MEMBERS:
                if name not in group.get('proxies', []):
                    group['proxies'].insert(0, name)
            print(f'Updated Proxies group (now {len(group["proxies"])} members)')
            break
    
    # Ensure Polymarket routing rules exist
    pm_rules = [
        'DOMAIN-SUFFIX,polymarket.com,Polymarket',
        'DOMAIN-SUFFIX,clob.polymarket.com,Polymarket',
        'DOMAIN-SUFFIX,gamma-api.polymarket.com,Polymarket',
        'DOMAIN-SUFFIX,strapi-matic.polymarket.com,Polymarket',
        'DOMAIN-SUFFIX,ws-subscriptions-clob.polymarket.com,Polymarket',
    ]
    existing_rules = parsed.get('rules', [])
    existing_rules = [r for r in existing_rules if 'polymarket' not in r.lower()]
    parsed['rules'] = pm_rules + existing_rules
    print(f'Updated routing rules (total: {len(parsed["rules"])})')
    
    # Dump YAML
    new_config = yaml.dump(parsed, default_flow_style=False, allow_unicode=True, sort_keys=False)
    
    # Validate
    reparse = yaml.safe_load(new_config)
    proxy_names = {p['name'] for p in reparse.get('proxies', [])}
    pm_group = next(g for g in reparse['proxy-groups'] if g['name'] == 'Polymarket')
    print(f'\nYAML validation OK')
    print(f'  Total proxies: {len(reparse["proxies"])}')
    print(f'  Polymarket group: {pm_group["type"]} with {len(pm_group["proxies"])} nodes')
    print(f'  PM nodes: {[n for n in pm_group["proxies"][:5]]}... (+{len(pm_group["proxies"])-5} more)')
    
    # Write to remote
    sftp = ssh.open_sftp()
    with sftp.open('/tmp/mihomo_config_eligible.yaml', 'w') as f:
        f.write(new_config)
    sftp.close()
    
    # Validate on remote
    remote_check = run("python3 -c \"import yaml; d=yaml.safe_load(open('/tmp/mihomo_config_eligible.yaml')); print('OK:', len(d.get('proxies',[])), 'proxies,', len(d.get('proxy-groups',[])), 'groups')\" 2>&1")
    print(f'Remote validation: {remote_check.strip()[:200]}')
    
    # Apply
    print('\n=== Applying config ===')
    print(run('echo kaiyic | sudo -S cp /tmp/mihomo_config_eligible.yaml /etc/mihomo/config.yaml 2>&1').strip())
    print(run('echo kaiyic | sudo -S systemctl restart mihomo 2>&1').strip())
    time.sleep(8)
    
    # Check status
    status = run('echo kaiyic | sudo -S systemctl status mihomo 2>&1 | head -10')
    print(f'mihomo: {status[:300]}')
    
    if 'active (running)' not in status:
        print('FAILED! Restoring backup...')
        print(run('echo kaiyic | sudo -S cp /etc/mihomo/config.yaml.bak.eligible /etc/mihomo/config.yaml 2>&1').strip())
        print(run('echo kaiyic | sudo -S systemctl restart mihomo 2>&1').strip())
        ssh.close()
        return
    
    # Wait for mihomo to initialize
    time.sleep(5)
    
    # Check Polymarket group
    pm_info = run('curl -s http://127.0.0.1:9090/proxies/Polymarket 2>&1')
    try:
        pm_data = json.loads(pm_info)
        print(f'\nPolymarket group: type={pm_data.get("type")}, now={pm_data.get("now","?")}')
        print(f'  nodes: {pm_data.get("all",[])}')
    except:
        print(f'PM group info: {pm_info[:200]}')
    
    # Test geoblock through current node
    print('\n=== Geoblock test ===')
    geo = run('curl -s -x http://127.0.0.1:7890 https://polymarket.com/api/geoblock 2>&1')
    print(f'  {geo.strip()[:200]}')
    
    # Test order API
    order = run('curl -s -x http://127.0.0.1:7890 -X POST https://clob.polymarket.com/order -H "Content-Type: application/json" -d \'{}\' 2>&1')
    print(f'  Order API: {order.strip()[:200]}')
    
    # Restart trading service
    print('\n=== Restarting trading service ===')
    print(run('echo kaiyic | sudo -S systemctl restart polymarket-arb 2>&1').strip())
    time.sleep(10)
    print(f'Service: {run("systemctl is-active polymarket-arb 2>&1").strip()}')
    
    # Verify CLOB client proxy
    logs = run('journalctl -u polymarket-arb --since "15 sec ago" --no-pager 2>/dev/null | grep -E "proxy|inject|JP|CLOB" | tail -5')
    for l in logs.splitlines():
        print(f'  {l[:200]}')
    
    ssh.close()
    print('\n=== Done! ===')

if __name__ == '__main__':
    main()
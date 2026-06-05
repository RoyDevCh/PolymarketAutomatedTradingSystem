#!/usr/bin/env python3
"""Update mihomo config to add Japan nodes and Polymarket proxy group.
This script reads the current config, adds JP nodes from the subscription,
adds a Polymarket group that forces JP routing, and restarts mihomo.
"""
import paramiko, os, time

SSH_HOST = '192.168.3.117'
SSH_USER = 'roy'
SSH_PASS = os.getenv('REMOTE_PASSWORD', 'kaiyic')

# JP nodes from the subscription (anytls type - fastest)
JP_NODES_ANYTLS = [
    {
        'name': '🇯🇵 日本01',
        'type': 'anytls',
        'server': 'aws-nrt.edge.qchwnd.moe',
        'port': 443,
        'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
        'sni': 'moe233-riolu-ce068da0-f2ca-6b9b-c3cb-7dc079ae6f9e.qchwnd.moe',
    },
    {
        'name': '🇯🇵 日本02',
        'type': 'anytls',
        'server': 'aws-nrt.edge.qchwnd.moe',
        'port': 443,
        'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
        'sni': 'moe233-riolu-8efefdb7-1701-a524-d925-844f02d32bf4.qchwnd.moe',
    },
    {
        'name': '🇯🇵 日本03',
        'type': 'anytls',
        'server': '0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org',
        'port': 443,
        'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
        'sni': 'moe233-riolu-ce068da0-f2ca-6b9b-c3cb-7dc079ae6f9e.qchwnd.moe',
    },
    {
        'name': '🇯🇵 日本04',
        'type': 'anytls',
        'server': '0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org',
        'port': 443,
        'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64',
        'sni': 'moe233-riolu-8efefdb7-1701-a524-d925-844f02d32bf4.qchwnd.moe',
    },
]

def build_yaml_node(node):
    """Build YAML node entry for mihomo config"""
    lines = [
        f"  - name: {node['name']}",
        f"    type: {node['type']}",
        f"    server: {node['server']}",
        f"    port: {node['port']}",
        f"    password: {node['password']}",
        f"    alpn:",
        f"      - h2",
        f"      - http/1.1",
        f"    skip-cert-verify: false",
        f"    udp: true",
        f"    sni: {node['sni']}",
    ]
    return '\n'.join(lines)


def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(SSH_HOST, username=SSH_USER, password=SSH_PASS, timeout=20)
    
    def run(cmd, t=15):
        _, stdout, stderr = ssh.exec_command(cmd, timeout=t)
        stdout.channel.settimeout(t)
        return (stdout.read() + stderr.read()).decode('utf-8','replace')
    
    # Step 1: Backup current config
    print("=== Step 1: Backup current mihomo config ===")
    print(run('echo kaiyic | sudo -S cp /etc/mihomo/config.yaml /etc/mihomo/config.yaml.bak.$(date +%s) 2>&1'))
    
    # Step 2: Read current config
    print("\n=== Step 2: Read current config ===")
    config = run('echo kaiyic | sudo -S cat /etc/mihomo/config.yaml 2>/dev/null')
    
    # Step 3: Build new config with JP nodes and Polymarket group
    print("\n=== Step 3: Build new config ===")
    
    # Check if JP nodes already exist
    if '🇯🇵 日本01' in config:
        print("  JP nodes already in config - will update")
        # Just need to add Polymarket group and rules
    else:
        # Add JP nodes after the last TW node (before proxy-groups)
        jp_yaml = '\n'.join(build_yaml_node(n) for n in JP_NODES_ANYTLS)
        
        # Find the line after last Taiwan node (before proxy-groups)
        lines = config.split('\n')
        insert_idx = None
        for i, line in enumerate(lines):
            if line.strip().startswith('- name: Proxies'):
                insert_idx = i
                break
        
        if insert_idx:
            lines.insert(insert_idx, jp_yaml)
            config = '\n'.join(lines)
            print(f"  Inserted JP nodes before Proxies group at line {insert_idx}")
    
    # Step 4: Add Polymarket proxy group (if not present)
    if 'Polymarket' not in config:
        # Find proxy-groups section and add Polymarket group
        pm_group = """  - name: Polymarket
    type: select
    proxies:
      - 🇯🇵 日本01
      - 🇯🇵 日本02
      - 🇯🇵 日本03
      - 🇯🇵 日本04
      - Proxies"""
        
        # Insert after the Proxies group definition
        lines = config.split('\n')
        for i, line in enumerate(lines):
            if line.strip() == 'proxies:' and i > 80:  # The proxy-groups proxies list
                # Find end of Proxies group proxies list
                # Insert Polymarket group here
                # Actually find the Taiwan-Fallback section and add after it
                pass

        # Better approach: just add it right before the rules section
        # But we need it inside proxy-groups section
        # Find "proxy-groups:" and add after the last group before rules:
        
        # Simpler: insert Polymarket policy rule that routes polymarket.com to JP
        # Add it in the proxy-groups section
        lines = config.split('\n')
        
        # Find proxy-groups line for Proxies list (the one under the groups section)
        # Insert Polymarket group after Taiwan-Fallback
        insert_idx = None
        for i, line in enumerate(lines):
            if 'name: Taiwan-Fallback' in line:
                # Find the end of Taiwan-Fallback group
                j = i + 1
                while j < len(lines) and (lines[j].startswith('    - ') or lines[j].startswith('    type:') or lines[j].startswith('    url:')):
                    j += 1
                insert_idx = j
                break
        
        if insert_idx:
            pm_lines = [
                "  - name: Polymarket",
                "    type: select",
                "    proxies:",
                "      - 🇯🇵 日本01",
                "      - 🇯🇵 日本02",
                "      - 🇯🇵 日本03", 
                "      - 🇯🇵 日本04",
                "      - Proxies",
            ]
            for k, pm_line in enumerate(pm_lines):
                lines.insert(insert_idx + k, pm_line)
            config = '\n'.join(lines)
            print("  Added Polymarket proxy group")
    
    # Step 5: Add Polymarket routing rules (before other rules)
    if 'polymarket' not in config.lower():
        # Add Polymarket rules at the beginning of rules section
        pm_rules = """    - DOMAIN-SUFFIX,polymarket.com,Polymarket
    - DOMAIN-SUFFIX,clob.polymarket.com,Polymarket
    - DOMAIN-SUFFIX,gamma-api.polymarket.com,Polymarket"""
        config = config.replace('rules:\n', f'rules:\n{pm_rules}\n')
        print("  Added Polymarket routing rules")
    
    # Step 6: Write new config
    print("\n=== Step 4: Write new config ===")
    # Write to temp file first
    sftp = ssh.open_sftp()
    with sftp.open('/tmp/mihomo_config_new.yaml', 'w') as f:
        f.write(config)
    sftp.close()
    
    # Copy to system location
    print(run('echo kaiyic | sudo -S cp /tmp/mihomo_config_new.yaml /etc/mihomo/config.yaml 2>&1'))
    
    # Step 7: Restart mihomo
    print("\n=== Step 5: Restart mihomo ===")
    print(run('echo kaiyic | sudo -S systemctl restart mihomo 2>&1'))
    time.sleep(5)
    print(run('echo kaiyic | sudo -S systemctl status mihomo 2>&1 | head -5'))
    
    # Step 8: Switch Proxies to JP-01 for general traffic too
    print("\n=== Step 6: Switch to JP-01 ===")
    print(run('curl -s -X PUT http://127.0.0.1:9090/proxies/Proxies -H "Content-Type: application/json" -d \'{"name": "🇯🇵 日本01"}\' 2>&1'))
    time.sleep(1)
    print(run('curl -s -X PUT http://127.0.0.1:9090/proxies/Polymarket -H "Content-Type: application/json" -d \'{"name": "🇯🇵 日本01"}\' 2>&1'))
    time.sleep(3)
    
    # Step 9: Verify
    print("\n=== Step 7: Verify ===")
    print(f"  Proxies: {run('curl -s http://127.0.0.1:9090/proxies/Proxies 2>&1 | python3 -c \"import sys,json;print(json.load(sys.stdin).get(\\\"now\\\",\\\"?\\\"))\" 2>&1').strip()}")
    print(f"  PM group: {run('curl -s http://127.0.0.1:9090/proxies/Polymarket 2>&1 | python3 -c \"import sys,json;print(json.load(sys.stdin).get(\\\"now\\\",\\\"?\\\"))\" 2>&1').strip()}")
    print(f"  Exit IP: {run('curl -s -x http://127.0.0.1:7890 https://httpbin.org/ip 2>&1').strip()[:100]}")
    
    # Step 10: Polymarket geoblock test
    print("\n=== Step 8: Polymarket geoblock test ===")
    geo = run('curl -s -x http://127.0.0.1:7890 https://polymarket.com/api/geoblock 2>&1')
    print(f"  {geo.strip()[:300]}")
    
    # Step 11: CLOB order API test
    print("\n=== Step 9: CLOB order API test ===")
    order = run('curl -s -x http://127.0.0.1:7890 -X POST https://clob.polymarket.com/order -H "Content-Type: application/json" -d \'{}\' 2>&1')
    print(f"  {order.strip()[:300]}")
    
    ssh.close()

if __name__ == '__main__':
    main()
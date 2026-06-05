#!/usr/bin/env python3
"""Add Japan nodes and Polymarket group to mihomo config - v3 (precise YAML)."""
import paramiko, os, time

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
    
    # Read current config
    config = run('echo kaiyic | sudo -S cat /etc/mihomo/config.yaml 2>/dev/null')
    
    # Backup
    print("=== Backing up ===")
    print(run('echo kaiyic | sudo -S cp /etc/mihomo/config.yaml /etc/mihomo/config.yaml.bak.v3 2>&1').strip())
    
    lines = config.split('\n')
    
    # === 1. Add JP proxy nodes before "proxy-groups:" ===
    # Format matches existing TW nodes: 2-space indent, same field order
    jp_nodes_block = """  - name: 🇯🇵 日本01
    type: anytls
    server: aws-nrt.edge.qchwnd.moe
    port: 443
    password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64
    alpn:
      - h2
      - http/1.1
    skip-cert-verify: false
    udp: true
    sni: moe233-riolu-ce068da0-f2ca-6b9b-c3cb-7dc079ae6f9e.qchwnd.moe
  - name: 🇯🇵 日本02
    type: anytls
    server: aws-nrt.edge.qchwnd.moe
    port: 443
    password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64
    alpn:
      - h2
      - http/1.1
    skip-cert-verify: false
    udp: true
    sni: moe233-riolu-8efefdb7-1701-a524-d925-844f02d32bf4.qchwnd.moe
  - name: 🇯🇵 日本03
    type: anytls
    server: 0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org
    port: 443
    password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64
    alpn:
      - h2
      - http/1.1
    skip-cert-verify: false
    udp: true
    sni: moe233-riolu-ce068da0-f2ca-6b9b-c3cb-7dc079ae6f9e.qchwnd.moe
  - name: 🇯🇵 日本04
    type: anytls
    server: 0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org
    port: 443
    password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64
    alpn:
      - h2
      - http/1.1
    skip-cert-verify: false
    udp: true
    sni: moe233-riolu-8efefdb7-1701-a524-d925-844f02d32bf4.qchwnd.moe"""

    new_lines = []
    for line in lines:
        if line.strip() == 'proxy-groups:':
            # Insert JP nodes before proxy-groups
            new_lines.append(jp_nodes_block)
            new_lines.append(line)  # proxy-groups:
        else:
            new_lines.append(line)
    
    lines = new_lines
    
    # === 2. Add Polymarket proxy group (after Taiwan-Fallback group) ===
    # Find end of Taiwan-Fallback group: it ends at "lazy: false" before "rules:"
    pm_group = """- name: Polymarket
  type: select
  proxies:
    - 🇯🇵 日本01
    - 🇯🇵 日本02
    - 🇯🇵 日本03
    - 🇯🇵 日本04
    - Proxies"""

    new_lines = []
    for i, line in enumerate(lines):
        new_lines.append(line)
        if 'lazy: false' in line and i > 80:  # Only after proxy-groups section
            new_lines.append(pm_group)
    
    lines = new_lines
    
    # === 3. Add Polymarket routing rules before existing rules ===
    pm_rules = """- DOMAIN-SUFFIX,polymarket.com,Polymarket
- DOMAIN-SUFFIX,clob.polymarket.com,Polymarket
- DOMAIN-SUFFIX,gamma-api.polymarket.com,Polymarket"""

    new_lines = []
    inserted_rules = False
    for line in lines:
        if line.strip() == 'rules:' and not inserted_rules:
            new_lines.append(line)
            new_lines.append(pm_rules)
            inserted_rules = True
        else:
            new_lines.append(line)
    
    lines = new_lines
    
    # Reconstruct
    new_config = '\n'.join(lines)
    
    # Validate YAML with Python
    print("\n=== Validating YAML locally ===")
    try:
        import yaml
        parsed = yaml.safe_load(new_config)
        print(f"  YAML OK! Proxies: {len(parsed.get('proxies', []))}, Groups: {len(parsed.get('proxy-groups', []))}")
        # Check JP nodes present
        proxy_names = [p['name'] for p in parsed.get('proxies', [])]
        jp_nodes = [n for n in proxy_names if '日本' in n or 'JP' in n]
        print(f"  JP nodes found: {jp_nodes}")
        # Check PM group present
        group_names = [g['name'] for g in parsed.get('proxy-groups', [])]
        print(f"  Groups: {group_names}")
    except Exception as e:
        print(f"  YAML validation error: {e}")
        # Try to find error line
        err_str = str(e)
        print(f"  Error: {err_str[:200]}")
    
    # Write to remote
    print("\n=== Writing config to remote ===")
    sftp = ssh.open_sftp()
    with sftp.open('/tmp/mihomo_config_jp_v3.yaml', 'w') as f:
        f.write(new_config)
    sftp.close()
    
    # Validate on remote with Python yaml
    print(run("python3 -c \"import yaml; d=yaml.safe_load(open('/tmp/mihomo_config_jp_v3.yaml')); print('Remote YAML OK'); print('Proxies:', len(d.get('proxies',[]))); print('Groups:', [g['name'] for g in d.get('proxy-groups',[]])]\" 2>&1"))
    
    # Apply config
    print("\n=== Applying config ===")
    print(run('echo kaiyic | sudo -S cp /tmp/mihomo_config_jp_v3.yaml /etc/mihomo/config.yaml 2>&1').strip())
    print(run('echo kaiyic | sudo -S systemctl restart mihomo 2>&1').strip())
    time.sleep(5)
    
    # Check status
    print("\n=== mihomo status ===")
    status = run('echo kaiyic | sudo -S systemctl status mihomo 2>&1 | head -15')
    print(status)
    
    if 'active (running)' not in status:
        print("\n  mihomo FAILED! Checking logs...")
        logs = run('echo kaiyic | sudo -S journalctl -u mihomo --since "30 sec ago" --no-pager 2>&1 | tail -10')
        print(logs)
        print("\n  Restoring backup...")
        print(run('echo kaiyic | sudo -S cp /etc/mihomo/config.yaml.bak.v3 /etc/mihomo/config.yaml 2>&1').strip())
        print(run('echo kaiyic | sudo -S systemctl restart mihomo 2>&1').strip())
        time.sleep(3)
        print(run('echo kaiyic | sudo -S systemctl status mihomo 2>&1 | head -5'))
        ssh.close()
        return
    
    # Switch proxy groups to JP
    print("\n=== Switching Polymarket group to 🇯🇵 日本01 ===")
    r1 = run('curl -s -X PUT http://127.0.0.1:9090/proxies/Polymarket -H "Content-Type: application/json" -d \'{\"name\": \"🇯🇵 日本01\"}\' 2>&1')
    print(f"  PM group switch: {r1[:100]}")
    
    r2 = run('curl -s -X PUT http://127.0.0.1:9090/proxies/Proxies -H "Content-Type: application/json" -d \'{\"name\": \"🇯🇵 日本01\"}\' 2>&1')
    print(f"  Proxies group switch: {r2[:100]}")
    time.sleep(3)
    
    # Verify
    print("\n=== Verifying JP routing ===")
    ip = run('curl -s -x http://127.0.0.1:7890 https://httpbin.org/ip 2>&1')
    print(f"  Exit IP: {ip.strip()[:200]}")
    
    geo = run('curl -s -x http://127.0.0.1:7890 https://polymarket.com/api/geoblock 2>&1')
    print(f"  Geoblock: {geo.strip()[:300]}")
    
    order = run('curl -s -x http://127.0.0.1:7890 -X POST https://clob.polymarket.com/order -H "Content-Type: application/json" -d \'{}\' 2>&1')
    print(f"  Order API: {order.strip()[:300]}")
    
    ssh.close()
    return True

if __name__ == '__main__':
    main()
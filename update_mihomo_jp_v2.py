#!/usr/bin/env python3
"""Properly add Japan nodes and Polymarket group to mihomo config.
Uses careful YAML manipulation to avoid format errors.
"""
import paramiko, os, time, re

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
    
    # Step 1: Read current config
    print("=== Reading current mihomo config ===")
    config = run('echo kaiyic | sudo -S cat /etc/mihomo/config.yaml 2>/dev/null')
    
    # Step 2: Backup
    print("=== Backing up ===")
    print(run('echo kaiyic | sudo -S cp /etc/mihomo/config.yaml /etc/mihomo/config.yaml.bak.prejp 2>&1').strip())
    
    # Step 3: Build new config properly
    # The current config has: proxies section with TW nodes, proxy-groups, and rules
    # We need to:
    # a) Add JP nodes after the TW proxy nodes (before proxy-groups)
    # b) Add JP nodes to the Proxies group member list
    # c) Add a Polymarket proxy group
    # d) Add Polymarket routing rules
    
    jp_nodes_yaml = """    - name: 🇯🇵 日本01
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

    # Find the last TW node line before proxy-groups
    lines = config.split('\n')
    
    # Find where to insert JP nodes: right before the "proxy-groups:" line
    insert_proxy_idx = None
    for i, line in enumerate(lines):
        if line.strip() == 'proxy-groups:':
            insert_proxy_idx = i
            break
    
    if insert_proxy_idx:
        # Insert JP nodes before proxy-groups
        new_lines = lines[:insert_proxy_idx] + [jp_nodes_yaml] + lines[insert_proxy_idx:]
        lines = new_lines
        print(f"  Inserted JP proxy nodes at line {insert_proxy_idx}")
    
    # Now add JP nodes to the Proxies group member list
    # Find "- name: Proxies" in proxy-groups section
    proxies_group_start = None
    for i, line in enumerate(lines):
        if '- name: Proxies' in line and 'Proxies' in line:
            proxies_group_start = i
            break
    
    if proxies_group_start:
        # Find the proxies list in Proxies group (indented "  - " lines)
        # Add JP nodes there
        jp_members = [
            "      - 🇯🇵 日本01",
            "      - 🇯🇵 日本02",
            "      - 🇯🇵 日本03",
            "      - 🇯🇵 日本04",
        ]
        # Find the Taiwan-Fallback reference in Proxies group and add before it
        for i in range(proxies_group_start, min(proxies_group_start + 20, len(lines))):
            if 'Taiwan-Fallback' in lines[i]:
                # Insert JP members before Taiwan-Fallback
                for j, member in enumerate(jp_members):
                    lines.insert(i + j, member)
                print(f"  Added JP nodes to Proxies group")
                break
    
    # Add Polymarket proxy group after Proxies group
    pm_group = """    - name: Polymarket
      type: select
      proxies:
        - 🇯🇵 日本01
        - 🇯🇵 日本02
        - 🇯🇵 日本03
        - 🇯🇵 日本04
        - Proxies"""
    
    # Find Taiwan-Fallback group and insert Polymarket group after it
    for i, line in enumerate(lines):
        if 'name: Taiwan-Fallback' in line:
            # Find end of Taiwan-Fallback group (next line starting with "  - name:")
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith('- name:'):
                j += 1
            # Insert PM group here
            lines.insert(j, pm_group)
            print(f"  Added Polymarket proxy group after Taiwan-Fallback")
            break
    
    # Add Polymarket routing rules at the beginning of rules section
    pm_rules = """    - DOMAIN-SUFFIX,polymarket.com,Polymarket
    - DOMAIN-SUFFIX,clob.polymarket.com,Polymarket
    - DOMAIN-SUFFIX,gamma-api.polymarket.com,Polymarket"""
    
    # Find "rules:" line and insert after it
    for i, line in enumerate(lines):
        if line.strip() == 'rules:':
            # Add PM rules with higher priority
            lines.insert(i + 1, pm_rules)
            print(f"  Added Polymarket routing rules")
            break
    
    # Reconstruct config
    new_config = '\n'.join(lines)
    
    # Step 4: Write to remote
    print("\n=== Writing new config ===")
    sftp = ssh.open_sftp()
    with sftp.open('/tmp/mihomo_config_jp.yaml', 'w') as f:
        f.write(new_config)
    sftp.close()
    
    # Validate YAML
    print("\n=== Validating YAML ===")
    validate = run('python3 -c "import yaml; yaml.safe_load(open(\'/tmp/mihomo_config_jp.yaml\')); print(\'YAML OK\')" 2>&1')
    print(f"  {validate.strip()[:200]}")
    
    if 'YAML OK' not in validate:
        # Show lines around the error
        err_line = None
        for part in validate.split():
            try:
                err_line = int(part.replace('line', '').replace(':', '').strip())
            except:
                pass
        if err_line:
            print(f"  Error at line {err_line}, showing context:")
            result_lines = new_config.split('\n')
            for i in range(max(0, err_line-5), min(len(result_lines), err_line+5)):
                print(f"  {i+1}: {result_lines[i]}")
        
        # Fallback: restore backup
        print("  YAML invalid, restoring backup...")
        print(run('echo kaiyic | sudo -S cp /etc/mihomo/config.yaml.bak.prejp /etc/mihomo/config.yaml 2>&1').strip())
        print(run('echo kaiyic | sudo -S systemctl restart mihomo 2>&1').strip())
        ssh.close()
        return
    
    # Step 5: Apply new config
    print("\n=== Applying new config ===")
    print(run('echo kaiyic | sudo -S cp /tmp/mihomo_config_jp.yaml /etc/mihomo/config.yaml 2>&1').strip())
    print(run('echo kaiyic | sudo -S systemctl restart mihomo 2>&1').strip())
    time.sleep(5)
    
    # Step 6: Check mihomo status
    print("\n=== mihomo status ===")
    status = run('echo kaiyic | sudo -S systemctl status mihomo 2>&1 | head -10')
    print(status)
    
    if 'active (running)' not in status:
        print("  ERROR: mihomo not running! Restoring backup...")
        print(run('echo kaiyic | sudo -S cp /etc/mihomo/config.yaml.bak.prejp /etc/mihomo/config.yaml 2>&1').strip())
        print(run('echo kaiyic | sudo -S systemctl restart mihomo 2>&1').strip())
        time.sleep(3)
        print(run('echo kaiyic | sudo -S systemctl status mihomo 2>&1 | head -5'))
        ssh.close()
        return
    
    # Step 7: Switch to JP-01
    print("\n=== Switching Polymarket group to 🇯🇵 日本01 ===")
    print(run('curl -s -X PUT http://127.0.0.1:9090/proxies/Polymarket -H "Content-Type: application/json" -d \'{"name": "🇯🇵 日本01"}\' 2>&1')[:100])
    time.sleep(2)
    
    # Also switch Proxies to JP-01 for general traffic
    print(run('curl -s -X PUT http://127.0.0.1:9090/proxies/Proxies -H "Content-Type: application/json" -d \'{"name": "🇯🇵 日本01"}\' 2>&1')[:100])
    time.sleep(2)
    
    # Step 8: Verify JP routing
    print("\n=== Verifying JP routing ===")
    
    # Verify proxy group
    print(f"  Polymarket group: {run('curl -s http://127.0.0.1:9090/proxies/Polymarket 2>&1')[:200]}")
    
    # Test exit IP
    print(f"\n  Exit IP: {run('curl -s -x http://127.0.0.1:7890 https://httpbin.org/ip 2>&1').strip()[:200]}")
    
    # Test geoblock
    print(f"  Geoblock: {run('curl -s -x http://127.0.0.1:7890 https://polymarket.com/api/geoblock 2>&1').strip()[:200]}")
    
    # Test CLOB order API
    print(f"  Order API: {run('curl -s -x http://127.0.0.1:7890 -X POST https://clob.polymarket.com/order -H \"Content-Type: application/json\" -d \'{}\' 2>&1').strip()[:200]}")
    
    ssh.close()

if __name__ == '__main__':
    main()
#!/usr/bin/env python3
"""Update mihomo config on remote server to add non-blocked proxy nodes."""
import paramiko, time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.3.117', username='roy', password='kaiyic', timeout=10)

# Write the update script to the server
update_script = r'''#!/usr/bin/env python3
import sys

# Read config
with open('/etc/mihomo/config.yaml', 'r') as f:
    content = f.read()

# Define new proxy nodes (non-blocked by Polymarket)
new_nodes_lines = [
    "- { name: 'HK-01', type: anytls, server: 44c9706d-874e-f8b7-05c0-aaaa04a800c7.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-7f0c47de-1ed5-2da6-22ed-921e51992120.qchwnd.moe }",
    "- { name: 'HK-02', type: anytls, server: 44c9706d-874e-f8b7-05c0-aaaa04a800c7.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-b94777dd-13e5-228d-ccdf-ea937be0c8ab.qchwnd.moe }",
    "- { name: 'KR-01', type: anytls, server: 0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-5e3746c6-b3a3-8086-d853-bd323b99bae2.qchwnd.moe }",
    "- { name: 'KR-02', type: anytls, server: jp.edge.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-5e3746c6-b3a3-8086-d853-bd323b99bae2.qchwnd.moe }",
    "- { name: 'ID-01', type: anytls, server: 46594d3d-2d7c-ffa2-2cc7-af4c6c347312.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-3a085f91-005a-c285-f2c7-b4565ef204f0.qchwnd.moe }",
    "- { name: 'TR-01', type: anytls, server: 0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-e8c6cfe7-e044-dca9-8f45-8e52fd32f4de.qchwnd.moe }",
]

# Add new nodes before proxy-groups section
if 'HK-01' not in content:
    new_nodes_text = '\n'.join(new_nodes_lines)
    content = content.replace('\nproxy-groups:', '\n' + new_nodes_text + '\nproxy-groups:')
    print('Added new proxy nodes')
else:
    print('HK-01 already exists, skipping')

# Update Polymarket proxy group
# Remove US/SG nodes, add HK/KR/ID/TR, keep JP for API
lines = content.split('\n')
new_lines = []
in_pmarket = False
pmarket_done = False

for i, line in enumerate(lines):
    if '- name: Polymarket' in line and not pmarket_done:
        in_pmarket = True
        new_lines.append(line)  # Keep the name line
        # Replace type with select
        continue
    elif in_pmarket:
        stripped = line.strip()
        if stripped.startswith('type:'):
            new_lines.append('  type: select')
            continue
        elif stripped.startswith('proxies:'):
            new_lines.append('  proxies:')
            continue
        elif stripped.startswith('- US-') or stripped.startswith('- SG-'):
            continue  # Skip blocked nodes
        elif stripped.startswith('- JP-'):
            new_lines.append(line)  # Keep JP nodes (API works)
            continue
        elif stripped.startswith('url:') or stripped.startswith('interval:') or stripped.startswith('tolerance:'):
            continue  # Remove url-test settings
        elif stripped.startswith('- name:') or (not stripped.startswith('-') and not stripped.startswith('  ') and stripped):
            # End of Polymarket group
            # Insert non-blocked nodes
            if not pmarket_done:
                new_lines.append('  - HK-01')
                new_lines.append('  - HK-02')
                new_lines.append('  - KR-01')
                new_lines.append('  - KR-02')
                new_lines.append('  - ID-01')
                new_lines.append('  - TR-01')
                pmarket_done = True
            in_pmarket = False
            new_lines.append(line)
            continue
        elif not stripped:
            # Empty line might end the group
            if not pmarket_done:
                new_lines.append('  - HK-01')
                new_lines.append('  - HK-02')
                new_lines.append('  - KR-01')
                new_lines.append('  - KR-02')
                new_lines.append('  - ID-01')
                new_lines.append('  - TR-01')
                pmarket_done = True
            in_pmarket = False
            new_lines.append(line)
            continue
        else:
            new_lines.append(line)
            continue
    else:
        new_lines.append(line)

content = '\n'.join(new_lines)

# Also add new nodes to Proxies group
if 'HK-01' not in content.split('- name: Proxies')[1].split('- name:')[0] if '- name: Proxies' in content else '':
    content = content.replace(
        '- name: Proxies\n  type: select\n  proxies:\n  - Polymarket\n  - Taiwan-Fallback',
        '- name: Proxies\n  type: select\n  proxies:\n  - Polymarket\n  - Taiwan-Fallback\n  - HK-01\n  - HK-02\n  - KR-01\n  - KR-02'
    )
    print('Added nodes to Proxies group')

with open('/etc/mihomo/config.yaml', 'w') as f:
    f.write(content)

print('Config updated!')
'''

# Write script to server
sftp = ssh.open_sftp()
with sftp.open('/home/roy/update_mihomo.py', 'w') as f:
    f.write(update_script)
sftp.close()

# Execute: backup + update
print("=== Step 1: Backup config ===")
stdin, stdout, stderr = ssh.exec_command('echo kaiyic | sudo -S cp /etc/mihomo/config.yaml /etc/mihomo/config.yaml.bak3 2>&1', timeout=10)
print(stdout.read().decode().strip()[:200])

print("\n=== Step 2: Update config ===")
stdin, stdout, stderr = ssh.exec_command('echo kaiyic | sudo -S python3 /home/roy/update_mihomo.py 2>&1', timeout=30)
out = stdout.read().decode('utf-8', errors='replace')
for line in out.split('\n'):
    if line.strip():
        print(line.strip()[:150])

print("\n=== Step 3: Restart mihomo ===")
stdin, stdout, stderr = ssh.exec_command('echo kaiyic | sudo -S systemctl restart mihomo 2>&1', timeout=15)
time.sleep(4)

stdin, stdout, stderr = ssh.exec_command('systemctl is-active mihomo 2>&1', timeout=10)
print(f"Mihomo status: {stdout.read().decode().strip()}")

# Step 4: Switch to HK-01 and test
print("\n=== Step 4: Switch to HK-01 ===")
stdin, stdout, stderr = ssh.exec_command('curl -s -X PUT http://127.0.0.1:9090/proxies/Polymarket -H "Content-Type: application/json" -d \'{"name": "HK-01"}\' 2>&1', timeout=10)
print(f"Switch result: {stdout.read().decode().strip()[:200]}")

time.sleep(2)

# Verify
print("\n=== Step 5: Verify HK-01 ===")
stdin, stdout, stderr = ssh.exec_command('curl -s http://127.0.0.1:9090/proxies/Polymarket 2>&1', timeout=10)
out = stdout.read().decode()
import json
try:
    data = json.loads(out)
    print(f"Current: {data.get('now', 'unknown')}")
    print(f"Proxies: {data.get('all', [])}")
except:
    print(out[:300])

# Step 6: Test geoblock
print("\n=== Step 6: Test geoblock via HK-01 ===")
stdin, stdout, stderr = ssh.exec_command('source ~/.proxyrc && curl -s -x http://127.0.0.1:7890 https://polymarket.com/api/geoblock 2>&1', timeout=15)
geo = stdout.read().decode().strip()
try:
    gd = json.loads(geo)
    print(f"blocked={gd.get('blocked')}, country={gd.get('country')}, region={gd.get('region')}")
    if gd.get('blocked'):
        print("*** STILL BLOCKED! Try another node ***")
    else:
        print("*** NOT BLOCKED! HK-01 works! ***")
except:
    print(f"Geoblock response: {geo[:200]}")

# Step 7: Test exit IP
print("\n=== Step 7: Check exit IP ===")
stdin, stdout, stderr = ssh.exec_command('source ~/.proxyrc && curl -s -x http://127.0.0.1:7890 https://httpbin.org/ip 2>&1', timeout=15)
print(f"Exit IP: {stdout.read().decode().strip()[:200]}")

# Step 8: Test CLOB API
print("\n=== Step 8: Test CLOB API ===")
stdin, stdout, stderr = ssh.exec_command('source ~/.proxyrc && curl -s -x http://127.0.0.1:7890 https://clob.polymarket.com/time 2>&1', timeout=15)
print(f"CLOB time: {stdout.read().decode().strip()[:200]}")

ssh.close()
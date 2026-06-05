#!/usr/bin/env python3
"""Update mihomo config: add non-blocked country nodes and update Polymarket group."""
import json, subprocess, time

# Step 1: Add non-blocked proxy nodes to mihomo config
# HK, KR, ID, TR nodes from Clash Verge config (not blocked by Polymarket)

# New proxy nodes to add (these are the same relay servers used by other nodes)
new_nodes_yaml = """
- { name: 'HK-01', type: anytls, server: 44c9706d-874e-f8b7-05c0-aaaa04a800c7.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-7f0c47de-1ed5-2da6-22ed-921e51992120.qchwnd.moe }
- { name: 'HK-02', type: anytls, server: 44c9706d-874e-f8b7-05c0-aaaa04a800c7.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-b94777dd-13e5-228d-ccdf-ea937be0c8ab.qchwnd.moe }
- { name: 'HK-03', type: anytls, server: 44c9706d-874e-f8b7-05c0-aaaa04a800c7.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-7f0c47de-1ed5-2da6-22ed-921e51992120.qchwnd.moe }
- { name: 'HK-04', type: anytls, server: 44c9706d-874e-f8b7-05c0-aaaa04a800c7.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-b94777dd-13e5-228d-ccdf-ea937be0c8ab.qchwnd.moe }
- { name: 'KR-01', type: anytls, server: 0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-5e3746c6-b3a3-8086-d853-bd323b99bae2.qchwnd.moe }
- { name: 'KR-02', type: anytls, server: jp.edge.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-5e3746c6-b3a3-8086-d853-bd323b99bae2.qchwnd.moe }
- { name: 'ID-01', type: anytls, server: 46594d3d-2d7c-ffa2-2cc7-af4c6c347312.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-3a085f91-005a-c285-f2c7-b4565ef204f0.qchwnd.moe }
- { name: 'ID-02', type: anytls, server: 46594d3d-2d7c-ffa2-2cc7-af4c6c347312.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-3a085f91-005a-c285-f2c7-b4565ef204f0.qchwnd.moe }
- { name: 'TR-01', type: anytls, server: 0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-e8c6cfe7-e044-dca9-8f45-8e52fd32f4de.qchwnd.moe }
- { name: 'TR-02', type: anytls, server: 0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-e8c6cfe7-e044-dca9-8f45-8e52fd32f4de.qchwnd.moe }
"""

# Write the update script
update_script = """#!/bin/bash
set -e

# Backup original config
echo "kaiyic" | sudo -S cp /etc/mihomo/config.yaml /etc/mihomo/config.yaml.bak2

# Add new proxy nodes before the proxy-groups section
echo "kaiyic" | sudo -S python3 << 'PYEOF'
import yaml
import shutil

with open('/etc/mihomo/config.yaml', 'r') as f:
    config = yaml.safe_load(f)

# Add new nodes
new_nodes = [
    {'name': 'HK-01', 'type': 'anytls', 'server': '44c9706d-874e-f8b7-05c0-aaaa04a800c7.relay.moe233.org', 'port': 443, 'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64', 'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True, 'sni': 'moe233-riolu-7f0c47de-1ed5-2da6-22ed-921e51992120.qchwnd.moe'},
    {'name': 'HK-02', 'type': 'anytls', 'server': '44c9706d-874e-f8b7-05c0-aaaa04a800c7.relay.moe233.org', 'port': 443, 'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64', 'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True, 'sni': 'moe233-riolu-b94777dd-13e5-228d-ccdf-ea937be0c8ab.qchwnd.moe'},
    {'name': 'HK-03', 'type': 'anytls', 'server': '44c9706d-874e-f8b7-05c0-aaaa04a800c7.relay.moe233.org', 'port': 443, 'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64', 'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True, 'sni': 'moe233-riolu-7f0c47de-1ed5-2da6-22ed-921e51992120.qchwnd.moe'},
    {'name': 'HK-04', 'type': 'anytls', 'server': '44c9706d-874e-f8b7-05c0-aaaa04a800c7.relay.moe233.org', 'port': 443, 'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64', 'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True, 'sni': 'moe233-riolu-b94777dd-13e5-228d-ccdf-ea937be0c8ab.qchwnd.moe'},
    {'name': 'KR-01', 'type': 'anytls', 'server': '0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org', 'port': 443, 'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64', 'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True, 'sni': 'moe233-riolu-5e3746c6-b3a3-8086-d853-bd323b99bae2.qchwnd.moe'},
    {'name': 'KR-02', 'type': 'anytls', 'server': 'jp.edge.moe233.org', 'port': 443, 'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64', 'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True, 'sni': 'moe233-riolu-5e3746c6-b3a3-8086-d853-bd323b99bae2.qchwnd.moe'},
    {'name': 'ID-01', 'type': 'anytls', 'server': '46594d3d-2d7c-ffa2-2cc7-af4c6c347312.relay.moe233.org', 'port': 443, 'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64', 'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True, 'sni': 'moe233-riolu-3a085f91-005a-c285-f2c7-b4565ef204f0.qchwnd.moe'},
    {'name': 'ID-02', 'type': 'anytls', 'server': '46594d3d-2d7c-ffa2-2cc7-af4c6c347312.relay.moe233.org', 'port': 443, 'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64', 'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True, 'sni': 'moe233-riolu-3a085f91-005a-c285-f2c7-b4565ef204f0.qchwnd.moe'},
    {'name': 'TR-01', 'type': 'anytls', 'server': '0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org', 'port': 443, 'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64', 'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True, 'sni': 'moe233-riolu-e8c6cfe7-e044-dca9-8f45-8e52fd32f4de.qchwnd.moe'},
    {'name': 'TR-02', 'type': 'anytls', 'server': '0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org', 'port': 443, 'password': '584351b2-f2a6-4152-b97f-7ab7a8c5fe64', 'alpn': ['h2', 'http/1.1'], 'skip-cert-verify': False, 'udp': True, 'sni': 'moe233-riolu-e8c6cfe7-e044-dca9-8f45-8e52fd32f4de.qchwnd.moe'},
]

# Add new nodes to proxies
existing_names = set(p['name'] for p in config.get('proxies', []))
for node in new_nodes:
    if node['name'] not in existing_names:
        config['proxies'].append(node)
        print(f"Added node: {node['name']}")
    else:
        print(f"Node already exists: {node['name']}")

# Update Polymarket proxy group - remove US and SG, add non-blocked nodes
for pg in config.get('proxy-groups', []):
    if pg['name'] == 'Polymarket':
        # Replace the proxy list with non-blocked countries only
        pg['proxies'] = ['HK-01', 'HK-02', 'HK-03', 'HK-04', 'KR-01', 'KR-02', 'ID-01', 'ID-02', 'TR-01', 'TR-02', 'JP-01', 'JP-02', 'JP-03', 'JP-04']
        # Change type from url-test to select for manual control
        pg['type'] = 'select'
        # Remove url-test specific fields
        if 'url' in pg:
            del pg['url']
        if 'interval' in pg:
            del pg['interval']
        if 'tolerance' in pg:
            del pg['tolerance']
        print(f"Updated Polymarket group: {pg['proxies']}")

# Write back
with open('/etc/mihomo/config.yaml', 'w') as f:
    yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

print("Config updated successfully!")
PYEOF

# Restart mihomo to load new config
echo "kaiyic" | sudo -S systemctl restart mihomo
sleep 3
echo "Mihomo restarted"
"""

# Write to file
with open('/tmp/update_mihomo_polymarket.sh', 'w') as f:
    f.write(update_script)

print("Update script created")
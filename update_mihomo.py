#!/usr/bin/env python3
"""
Update remote mihomo config to add Polymarket-compatible nodes.

Adds US/JP/SG nodes from local Clash Verge config to remote mihomo,
creates a Polymarket proxy group with url-test auto-selection,
and adds rules to route Polymarket traffic through that group.
"""
import paramiko
import re

SSH_HOST = "192.168.3.117"
SSH_USER = "roy"
SSH_PASS = "kaiyic"

# Nodes to add - US, JP, SG nodes that can bypass Polymarket's geo-block
# Polymarket allows: US, JP, SG, UK, FR, DE, CA, etc.
# These are copied from local Clash Verge Rev config
NEW_NODES = [
    # US nodes (primary choice for Polymarket)
    "{ name: '\\U0001f1fa\\U0001f1f8 美国01', type: anytls, server: raksmart-sjc.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-7f0c47de-1ed5-2da6-22ed-921e51992120.qchwnd.moe }",
    "{ name: '\\U0001f1fa\\U0001f1f8 美国02', type: anytls, server: raksmart-sjc.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-b94777dd-13e5-228d-ccdf-ea937be0c8ab.qchwnd.moe }",
    "{ name: '\\U0001f1fa\\U0001f1f8 美国03', type: anytls, server: raksmart-sjc.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-9ceea1e7-8f6a-c055-33ae-2da3dcc9d3b5.qchwnd.moe }",
    "{ name: '\\U0001f1fa\\U0001f1f8 美国04', type: anytls, server: raksmart-sjc.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-b94777dd-13e5-228d-ccdf-ea937be0c8ab.qchwnd.moe }",
    "{ name: '\\U0001f1fa\\U0001f1f8 美国05', type: anytls, server: raksmart-sjc.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-9ceea1e7-8f6a-c055-33ae-2da3dcc9d3b5.qchwnd.moe }",
    # JP nodes (backup)
    "{ name: '\\U0001f1ef\\U0001f1f5 日本01', type: anytls, server: aws-nrt.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-ce068da0-f2ca-6b9b-c3cb-7dc079ae6f9e.qchwnd.moe }",
    "{ name: '\\U0001f1ef\\U0001f1f5 日本02', type: anytls, server: aws-nrt.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-8efefdb7-1701-a524-d925-844f02d32bf4.qchwnd.moe }",
    "{ name: '\\U0001f1ef\\U0001f1f5 日本03', type: anytls, server: 0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-ce068da0-f2ca-6b9b-c3cb-7dc079ae6f9e.qchwnd.moe }",
    "{ name: '\\U0001f1ef\\U0001f1f5 日本04', type: anytls, server: 0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-8efefdb7-1701-a524-d925-844f02d32bf4.qchwnd.moe }",
    # SG nodes (backup)
    "{ name: '\\U0001f1f8\\U0001f1ec 新加坡01', type: anytls, server: 46594d3d-2d7c-ffa2-2cc7-af4c6c347312.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-655d3987-e9a4-935a-877e-a91ce6fe776e.qchwnd.moe }",
    "{ name: '\\U0001f1f8\\U0001f1ec 新加坡02', type: anytls, server: 46594d3d-2d7c-ffa2-2cc7-af4c6c347312.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-c4c745f3-e49f-e7ac-b9d6-9a0fbe8511f0.qchwnd.moe }",
]

# Build the new config additions
# 1. New proxy nodes
PROXY_NODE_LINES = []
for node in NEW_NODES:
    # Convert {name: '🇺🇸 美国01', ...} format to YAML - with proper indent
    node = node.strip().strip('{').strip('}')
    # Parse key=value pairs
    props = {}
    current_key = ""
    current_val = ""
    in_quote = False
    in_bracket = 0
    for ch in node:
        if ch == "'" and not in_bracket:
            in_quote = not in_quote
            current_val += ch
        elif ch == '[' and not in_quote:
            in_bracket += 1
            current_val += ch
        elif ch == ']' and not in_quote:
            in_bracket -= 1
            current_val += ch
        elif ch == ',' and not in_quote and in_bracket == 0:
            # End of key=value pair
            k, _, v = current_val.strip().partition('=')
            if k.strip():
                props[k.strip()] = v.strip()
            current_val = ""
        else:
            current_val += ch
    if current_val.strip():
        k, _, v = current_val.strip().partition('=')
        if k.strip():
            props[k.strip()] = v.strip()

    PROXY_NODE_LINES.append(node)

print(f"Adding {len(NEW_NODES)} new proxy nodes")

# Actually, let's just write the YAML directly since parsing is messy
# We'll use sed/patch approach on the remote server
SSH = paramiko.SSHClient()
SSH.set_missing_host_key_policy(paramiko.AutoAddPolicy())
SSH.connect(SSH_HOST, username=SSH_USER, password=SSH_PASS, timeout=10)

# Step 1: Backup the current config
print("Step 1: Backing up current config...")
stdin, stdout, stderr = SSH.exec_command(
    'echo kaiyic | sudo -S cp /etc/mihomo/config.yaml /etc/mihomo/config.yaml.bak 2>&1',
    timeout=10
)
print(stdout.read().decode().strip())

# Step 2: Add new proxy nodes right before proxy-groups section
print("\nStep 2: Adding proxy nodes...")
proxies_yaml = """- { name: 'US-01', type: anytls, server: raksmart-sjc.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-7f0c47de-1ed5-2da6-22ed-921e51992120.qchwnd.moe }
- { name: 'US-02', type: anytls, server: raksmart-sjc.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-b94777dd-13e5-228d-ccdf-ea937be0c8ab.qchwnd.moe }
- { name: 'US-03', type: anytls, server: raksmart-sjc.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-9ceea1e7-8f6a-c055-33ae-2da3dcc9d3b5.qchwnd.moe }
- { name: 'US-04', type: anytls, server: raksmart-sjc.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-b94777dd-13e5-228d-ccdf-ea937be0c8ab.qchwnd.moe }
- { name: 'US-05', type: anytls, server: raksmart-sjc.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-9ceea1e7-8f6a-c055-33ae-2da3dcc9d3b5.qchwnd.moe }
- { name: 'JP-01', type: anytls, server: aws-nrt.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-ce068da0-f2ca-6b9b-c3cb-7dc079ae6f9e.qchwnd.moe }
- { name: 'JP-02', type: anytls, server: aws-nrt.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-8efefdb7-1701-a524-d925-844f02d32bf4.qchwnd.moe }
- { name: 'JP-03', type: anytls, server: 0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-ce068da0-f2ca-6b9b-c3cb-7dc079ae6f9e.qchwnd.moe }
- { name: 'JP-04', type: anytls, server: 0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-8efefdb7-1701-a524-d925-844f02d32bf4.qchwnd.moe }
- { name: 'SG-01', type: anytls, server: 46594d3d-2d7c-ffa2-2cc7-af4c6c347312.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-655d3987-e9a4-935a-877e-a91ce6fe776e.qchwnd.moe }
- { name: 'SG-02', type: anytls, server: 46594d3d-2d7c-ffa2-2cc7-af4c6c347312.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-c4c745f3-e49f-e7ac-b9d6-9a0fbe8511f0.qchwnd.moe }"""

# Write the patch script
patch_script = r"""#!/bin/bash
# Add Polymarket-compatible proxy nodes to mihomo config
set -e

CONFIG="/etc/mihomo/config.yaml"

# Backup already done

# Get line number of proxy-groups section
GROUP_LINE=$(grep -n "^proxy-groups:" "$CONFIG" | head -1 | cut -d: -f1)
echo "proxy-groups at line: $GROUP_LINE"

# New proxy nodes to insert before proxy-groups
NODES='
- { name: '\''US-01'\'', type: anytls, server: raksmart-sjc.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-7f0c47de-1ed5-2da6-22ed-921e51992120.qchwnd.moe }
- { name: '\''US-02'\'', type: anytls, server: raksmart-sjc.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-b94777dd-13e5-228d-ccdf-ea937be0c8ab.qchwnd.moe }
- { name: '\''US-03'\'', type: anytls, server: raksmart-sjc.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-9ceea1e7-8f6a-c055-33ae-2da3dcc9d3b5.qchwnd.moe }
- { name: '\''US-04'\'', type: anytls, server: raksmart-sjc.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-b94777dd-13e5-228d-ccdf-ea937be0c8ab.qchwnd.moe }
- { name: '\''US-05'\'', type: anytls, server: raksmart-sjc.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-9ceea1e7-8f6a-c055-33ae-2da3dcc9d3b5.qchwnd.moe }
- { name: '\''JP-01'\'', type: anytls, server: aws-nrt.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-ce068da0-f2ca-6b9b-c3cb-7dc079ae6f9e.qchwnd.moe }
- { name: '\''JP-02'\'', type: anytls, server: aws-nrt.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-8efefdb7-1701-a524-d925-844f02d32bf4.qchwnd.moe }
- { name: '\''JP-03'\'', type: anytls, server: 0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-ce068da0-f2ca-6b9b-c3cb-7dc079ae6f9e.qchwnd.moe }
- { name: '\''JP-04'\'', type: anytls, server: 0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-8efefdb7-1701-a524-d925-844f02d32bf4.qchwnd.moe }
- { name: '\''SG-01'\'', type: anytls, server: 46594d3d-2d7c-ffa2-2cc7-af4c6c347312.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-655d3987-e9a4-935a-877e-a91ce6fe776e.qchwnd.moe }
- { name: '\''SG-02'\'', type: anytls, server: 46594d3d-2d7c-ffa2-2cc7-af4c6c347312.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-c4c745f3-e49f-e7ac-b9d6-9a0fbe8511f0.qchwnd.moe }'

# Insert nodes before proxy-groups
echo "$NODES" | sudo tee -a "$CONFIG" > /dev/null
# Actually need to insert before proxy-groups, not append
# Better approach: use Python to modify the config
echo "Nodes added"
"""

# Instead of complex shell scripting, let's use Python to modify the config on the remote server
# Read the config, modify it, write it back

print("Reading remote config...")
stdin, stdout, stderr = SSH.exec_command('echo kaiyic | sudo -S cat /etc/mihomo/config.yaml 2>/dev/null', timeout=15)
remote_config = stdout.read().decode('utf-8', errors='replace')

print(f"Config size: {len(remote_config)} bytes, {len(remote_config.splitlines())} lines")

# Insert new nodes before proxy-groups section
lines = remote_config.splitlines()
new_lines = []
inserted = False

# Proxy node definitions to add
proxy_additions = """- { name: 'US-01', type: anytls, server: raksmart-sjc.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-7f0c47de-1ed5-2da6-22ed-921e51992120.qchwnd.moe }
- { name: 'US-02', type: anytls, server: raksmart-sjc.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-b94777dd-13e5-228d-ccdf-ea937be0c8ab.qchwnd.moe }
- { name: 'US-03', type: anytls, server: raksmart-sjc.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-9ceea1e7-8f6a-c055-33ae-2da3dcc9d3b5.qchwnd.moe }
- { name: 'US-04', type: anytls, server: raksmart-sjc.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-b94777dd-13e5-228d-ccdf-ea937be0c8ab.qchwnd.moe }
- { name: 'US-05', type: anytls, server: raksmart-sjc.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-9ceea1e7-8f6a-c055-33ae-2da3dcc9d3b5.qchwnd.moe }
- { name: 'JP-01', type: anytls, server: aws-nrt.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-ce068da0-f2ca-6b9b-c3cb-7dc079ae6f9e.qchwnd.moe }
- { name: 'JP-02', type: anytls, server: aws-nrt.edge.qchwnd.moe, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-8efefdb7-1701-a524-d925-844f02d32bf4.qchwnd.moe }
- { name: 'JP-03', type: anytls, server: 0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-ce068da0-f2ca-6b9b-c3cb-7dc079ae6f9e.qchwnd.moe }
- { name: 'JP-04', type: anytls, server: 0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-8efefdb7-1701-a524-d925-844f02d32bf4.qchwnd.moe }
- { name: 'SG-01', type: anytls, server: 46594d3d-2d7c-ffa2-2cc7-af4c6c347312.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-655d3987-e9a4-935a-877e-a91ce6fe776e.qchwnd.moe }
- { name: 'SG-02', type: anytls, server: 46594d3d-2d7c-ffa2-2cc7-af4c6c347312.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-c4c745f3-e49f-e7ac-b9d6-9a0fbe8511f0.qchwnd.moe }"""

# New proxy group for Polymarket (url-test auto-selects fastest)
polymarket_group = """- name: Polymarket
  type: url-test
  proxies:
  - US-01
  - US-02
  - US-03
  - US-04
  - US-05
  - JP-01
  - JP-02
  - JP-03
  - JP-04
  - SG-01
  - SG-02
  url: 'https://clob.polymarket.com/time'
  interval: 300
  tolerance: 50"""

# Polymarket domain rules (insert before MATCH rule)
polymarket_rules = """- DOMAIN-SUFFIX,polymarket.com,Polymarket
- DOMAIN-SUFFIX,gamma-api.polymarket.com,Polymarket
- DOMAIN-SUFFIX,clob.polymarket.com,Polymarket
- DOMAIN,polymarket.com,Polymarket"""

for line in lines:
    if line.strip() == "proxy-groups:" and not inserted:
        # Insert proxy nodes before proxy-groups
        new_lines.extend(proxy_additions.splitlines())
        new_lines.append(line)
        inserted = True
    elif line.strip() == "- name: Proxies" and "- name: Taiwan-Fallback" not in "\n".join(lines[max(0, lines.index(line)-2):lines.index(line)+5]):
        # Add Polymarket group to Proxies selection list
        new_lines.append(line)
    else:
        new_lines.append(line)

# Add Polymarket group after existing proxy-groups
# Find Taiwan-Fallback group end and add Polymarket group
config_with_nodes = "\n".join(new_lines)

# Add Polymarket proxy group
proxy_groups_end = config_with_nodes.find("rules:")
if proxy_groups_end > 0:
    # Find the last line of Taiwan-Fallback definition
    config_with_groups = config_with_nodes[:proxy_groups_end] + polymarket_group + "\n" + config_with_nodes[proxy_groups_end:]
else:
    config_with_groups = config_with_nodes + "\n" + polymarket_group

# Add Polymarket rules before MATCH rule
match_line = "- MATCH,Proxies"
if match_line in config_with_groups:
    config_final = config_with_groups.replace(match_line, polymarket_rules + "\n" + match_line)
else:
    config_final = config_with_groups

# Add Polymarket to Proxies selection
config_final = config_final.replace(
    "- name: Proxies\n  type: select\n  proxies:\n  - Taiwan-Fallback",
    "- name: Proxies\n  type: select\n  proxies:\n  - Polymarket\n  - Taiwan-Fallback"
)

# Write the modified config back
print(f"\nNew config size: {len(config_final)} bytes, {len(config_final.splitlines())} lines")

# Upload via SFTP to a temp file, then move it with sudo
sftp = SSH.open_sftp()
with sftp.open("/tmp/mihomo_config_new.yaml", "w") as f:
    f.write(config_final)
sftp.close()

# Move to mihomo config dir with sudo
stdin, stdout, stderr = SSH.exec_command(
    "echo kaiyic | sudo -S cp /tmp/mihomo_config_new.yaml /etc/mihomo/config.yaml 2>&1",
    timeout=10
)
print(f"Copy result: {stdout.read().decode().strip()}")

# Restart mihomo
print("\nStep 3: Restarting mihomo...")
stdin, stdout, stderr = SSH.exec_command(
    "echo kaiyic | sudo -S systemctl restart mihomo 2>&1",
    timeout=15
)
print(f"Restart result: {stdout.read().decode().strip()}")

import time
time.sleep(3)

# Verify mihomo is running
stdin, stdout, stderr = SSH.exec_command("echo kaiyic | sudo -S systemctl status mihomo 2>&1 | head -5", timeout=10)
print(f"\nStatus: {stdout.read().decode().strip()[:300]}")

# Check if Polymarket group exists
stdin, stdout, stderr = SSH.exec_command("echo kaiyic | sudo -S grep 'Polymarket' /etc/mihomo/config.yaml 2>/dev/null | head -5", timeout=10)
print(f"\nPolymarket rules in config: {stdout.read().decode().strip()[:500]}")

# Check mihomo API for new proxy group
time.sleep(5)
stdin, stdout, stderr = SSH.exec_command("curl -s http://127.0.0.1:9090/proxies/Polymarket 2>&1 | head -10", timeout=10)
print(f"\nPolymarket group in API: {stdout.read().decode().strip()[:500]}")

SSH.close()
print("\nDone!")
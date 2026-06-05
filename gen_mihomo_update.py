#!/usr/bin/env python3
"""Update mihomo config to add non-blocked proxy nodes for Polymarket."""
import subprocess, json, time

def run(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    return result.stdout.strip()

# Step 1: Add new proxy nodes via sed (append before proxy-groups)
# We'll use Python via SSH to do this properly
print("=== Adding non-blocked country nodes to mihomo ===")

# New nodes YAML (HK, KR, ID, TR - all not blocked by Polymarket)
new_nodes = """- { name: 'HK-01', type: anytls, server: 44c9706d-874e-f8b7-05c0-aaaa04a800c7.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-7f0c47de-1ed5-2da6-22ed-921e51992120.qchwnd.moe }
- { name: 'HK-02', type: anytls, server: 44c9706d-874e-f8b7-05c0-aaaa04a800c7.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-b94777dd-13e5-228d-ccdf-ea937be0c8ab.qchwnd.moe }
- { name: 'HK-03', type: anytls, server: 44c9706d-874e-f8b7-05c0-aaaa04a800c7.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-7f0c47de-1ed5-2da6-22ed-921e51992120.qchwnd.moe }
- { name: 'HK-04', type: anytls, server: 44c9706d-874e-f8b7-05c0-aaaa04a800c7.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-b94777dd-13e5-228d-ccdf-ea937be0c8ab.qchwnd.moe }
- { name: 'KR-01', type: anytls, server: 0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-5e3746c6-b3a3-8086-d853-bd323b99bae2.qchwnd.moe }
- { name: 'KR-02', type: anytls, server: jp.edge.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-5e3746c6-b3a3-8086-d853-bd323b99bae2.qchwnd.moe }
- { name: 'ID-01', type: anytls, server: 46594d3d-2d7c-ffa2-2cc7-af4c6c347312.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-3a085f91-005a-c285-f2c7-b4565ef204f0.qchwnd.moe }
- { name: 'ID-02', type: anytls, server: 46594d3d-2d7c-ffa2-2cc7-af4c6c347312.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-3a085f91-005a-c285-f2c7-b4565ef204f0.qchwnd.moe }
- { name: 'TR-01', type: anytls, server: 0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-e8c6cfe7-e044-dca9-8f45-8e52fd32f4de.qchwnd.moe }
- { name: 'TR-02', type: anytls, server: 0ec6449b-5460-846b-146b-76070b8d948f.relay.moe233.org, port: 443, password: 584351b2-f2a6-4152-b97f-7ab7a8c5fe64, alpn: [h2, http/1.1], skip-cert-verify: false, udp: true, sni: moe233-riolu-e8c6cfe7-e044-dca9-8f45-8e52fd32f4de.qchwnd.moe }"""

# Write to temp file
with open('/tmp/mihomo_new_nodes.yaml', 'w') as f:
    f.write(new_nodes)

print("New nodes YAML written to /tmp/mihomo_new_nodes.yaml")
print("""
Now run on the server:
1. Backup config: sudo cp /etc/mihomo/config.yaml /etc/mihomo/config.yaml.bak2
2. Insert new nodes: sed -i '/^proxy-groups:/e cat /tmp/mihomo_new_nodes.yaml' /etc/mihomo/config.yaml
3. Update Polymarket group proxies
4. Restart mihomo: sudo systemctl restart mihomo
5. Switch to HK-01: curl -X PUT http://127.0.0.1:9090/proxies/Polymarket -H 'Content-Type: application/json' -d '{"name": "HK-01"}'
6. Test geoblock: curl -s -x http://127.0.0.1:7890 https://polymarket.com/api/geoblock
""")
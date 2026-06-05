"""Check mihomo proxy nodes and their delays"""
import json, urllib.request

# Get all proxies from mihomo API
resp = urllib.request.urlopen("http://127.0.0.1:9090/proxies")
data = json.loads(resp.read())

print("=== All proxy groups ===")
for name, info in data.get("proxies", {}).items():
    ptype = info.get("type", "")
    if ptype in ["Selector", "Fallback", "URLTest"]:
        now = info.get("now", "")
        all_nodes = info.get("all", [])
        print(f"Group: {repr(name)} (type={ptype}, now={repr(now)})")
        print(f"  Nodes ({len(all_nodes)}): {all_nodes[:5]}...")

print("\n=== All proxy nodes with delay ===")
for name, info in data.get("proxies", {}).items():
    ptype = info.get("type", "")
    if ptype in ["anytls", "Shadowsocks", "Vmess", "Vless", "Trojan", "ss"]:
        # Name may contain emoji - clean it
        clean_name = "".join(c for c in name if ord(c) < 128).strip()
        history = info.get("history", [])
        delay = history[-1].get("delay", 0) if history else 0
        server = info.get("server", "")
        port = info.get("port", "")
        print(f"  {clean_name}: delay={delay}ms, server={server}:{port}")

# Check Taiwan-Fallback group detail
print("\n=== Taiwan-Fallback detail ===")
resp2 = urllib.request.urlopen("http://127.0.0.1:9090/proxies/Taiwan-Fallback")
data2 = json.loads(resp2.read())
now = data2.get("now", "")
all_nodes = data2.get("all", [])
print(f"Current node: {repr(now)}")
print(f"All nodes: {all_nodes}")

# Test URL delay for each node
print("\n=== Testing delay to Polymarket for each node ===")
import base64
for node in all_nodes:
    # Use mihomo API to test delay
    encoded_name = base64.b64encode(node.encode()).decode()
    url = f"http://127.0.0.1:9090/proxies/{encoded_name}/delay?timeout=5000&url=https://clob.polymarket.com/time"
    try:
        resp3 = urllib.request.urlopen(url, timeout=10)
        result = json.loads(resp3.read())
        delay = result.get("delay", "N/A")
        clean_node = "".join(c for c in node if ord(c) < 128).strip()
        print(f"  {clean_node}: {delay}ms to clob.polymarket.com")
    except Exception as e:
        clean_node = "".join(c for c in node if ord(c) < 128).strip()
        print(f"  {clean_node}: Error - {e}")
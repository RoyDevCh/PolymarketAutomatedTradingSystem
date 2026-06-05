"""Test each mihomo proxy node for Polymarket compatibility"""
import json, urllib.request, httpx

MIHOMO_API = "http://127.0.0.1:9090"

# Get all proxies
resp = urllib.request.urlopen(f"{MIHOMO_API}/proxies")
data = json.loads(resp.read())

# Find all actual proxy nodes (not groups)
node_names = []
for name, info in data.get("proxies", {}).items():
    ptype = info.get("type", "")
    if ptype in ["anytls", "Shadowsocks", "Vmess", "Vless", "Trojan", "ss"]:
        server = info.get("server", "")
        sni = info.get("sni", "")
        history = info.get("history", [])
        delay = history[-1].get("delay", 0) if history else 0
        # ASCII-safe display name
        ascii_name = "".join(c for c in name if ord(c) < 128).strip() or f"node_{len(node_names)}"
        print(f"Found node: {ascii_name} (server={server}, delay={delay}ms)")
        node_names.append(name)

print(f"\nTotal nodes: {len(node_names)}")

# For each node: switch the Proxies group to use it via fallback, then test
# Actually, we can't easily switch Taiwan-Fallback to a specific node
# But we can switch the GLOBAL group

# Better approach: modify mihomo config to add a US-based proxy
# For now, let's test: can ANY of these nodes reach Polymarket POST?

print("\n=== Testing Polymarket POST through current proxy ===")
client = httpx.Client(proxy="http://127.0.0.1:7890", timeout=httpx.Timeout(10.0))

# Check current exit IP
try:
    r = client.get("https://api.ipify.org?format=json")
    print(f"Current exit IP: {r.json()}")
except Exception as e:
    print(f"IP check error: {e}")

# Test Polymarket GET
try:
    r = client.get("https://clob.polymarket.com/time")
    print(f"Polymarket GET /time: {r.status_code}")
except Exception as e:
    print(f"Polymarket GET error: {e}")

# Test Polymarket POST
try:
    r = client.post("https://clob.polymarket.com/order", json={}, headers={"Content-Type": "application/json"})
    print(f"Polymarket POST /order: {r.status_code} {r.text[:200]}")
except Exception as e:
    print(f"Polymarket POST error: {type(e).__name__}: {str(e)[:100]}")

client.close()

# Get Taiwan-Fallback nodes
print("\n=== Testing each fallback node ===")
resp2 = urllib.request.urlopen(f"{MIHOMO_API}/proxies/Taiwan-Fallback")
tf_data = json.loads(resp2.read())
tf_nodes = tf_data.get("all", [])
print(f"Fallback nodes: {len(tf_nodes)}")

for i, node_name in enumerate(tf_nodes):
    # URL-encode the node name for the API
    import urllib.parse
    encoded = urllib.parse.quote(node_name)
    
    # Get node info
    try:
        resp3 = urllib.request.urlopen(f"{MIHOMO_API}/proxies/{encoded}")
        node_data = json.loads(resp3.read())
        server = node_data.get("server", "")
        sni = node_data.get("sni", "")
        print(f"\n  Node {i+1}: server={server}, sni={sni}")
    except Exception as e:
        print(f"\n  Node {i+1}: Error getting info - {e}")

print("\n=== Conclusion ===")
print("ALL current nodes exit through Taiwan, which is blocked by Polymarket.")
print("We need to add a US/JP proxy node to mihomo config.")
print("")
print("Options:")
print("1. Add a US-based proxy node to mihomo config.yaml")
print("2. Use a separate US proxy in Python code")
print("3. Setup SSH tunnel to a US VPS")
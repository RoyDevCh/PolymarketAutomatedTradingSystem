"""Check mihomo proxy nodes and test different exits for Polymarket compatibility"""
import json, urllib.request, urllib.parse

# Get all proxies
resp = urllib.request.urlopen("http://127.0.0.1:9090/proxies")
data = json.loads(resp.read())

# Find each anytls node and its server
print("=== Proxy node details ===")
nodes = {}
for name, info in data.get("proxies", {}).items():
    ptype = info.get("type", "")
    if ptype == "anytls":
        server = info.get("server", "")
        port = info.get("port", "")
        sni = info.get("sni", "")
        history = info.get("history", [])
        delay = history[-1].get("delay", 0) if history else 0
        # Get ASCII-safe name
        ascii_name = "".join(c for c in name if ord(c) < 128).strip() or name
        print(f"  {ascii_name}: server={server}, port={port}, sni={sni}, delay={delay}ms")
        nodes[name] = info

# Check what exit IP each node gives us
print("\n=== Testing exit IPs ===")
for name in nodes:
    ascii_name = "".join(c for c in name if ord(c) < 128).strip() or name
    # Switch the GLOBAL proxy to this node temporarily
    try:
        url = "http://127.0.0.1:9090/proxies/GLOBAL"
        req = urllib.request.Request(url, data=json.dumps({"name": name}).encode(), method="PUT")
        req.add_header("Content-Type", "application/json")
        resp = urllib.request.urlopen(req, timeout=5)
        print(f"  Switched GLOBAL to {ascii_name}")
    except Exception as e:
        print(f"  Failed to switch GLOBAL to {ascii_name}: {e}")
        continue

    # Now test the exit IP through this node
    # We need to use a different proxy that routes through GLOBAL
    # Actually, the Proxies group uses Taiwan-Fallback which uses these nodes
    # Let's just test IP through each node via direct SOCKS5

    import httpx
    # Use the node through mihomo's SOCKS proxy
    try:
        client = httpx.Client(proxy="http://127.0.0.1:7890", timeout=httpx.Timeout(10.0))
        r = client.get("https://api.ipify.org?format=json")
        ip_info = r.json()
        print(f"  Exit IP: {ip_info}")
        
        # Also test Polymarket POST
        r2 = client.post("https://clob.polymarket.com/order", json={}, headers={"Content-Type": "application/json"})
        print(f"  Polymarket POST: {r2.status_code} {r2.text[:100]}")
        client.close()
    except Exception as e:
        print(f"  Error: {e}")

print("\nDone testing")
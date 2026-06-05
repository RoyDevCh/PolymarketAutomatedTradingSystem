"""Test each proxy node for Polymarket compatibility"""
import httpx
import json
import urllib.request
import time

MIHOMO_API = "http://127.0.0.1:9090"
PROXY = "http://127.0.0.1:7890"

nodes = ["US-01", "US-02", "US-03", "US-04", "US-05", "JP-01", "JP-02", "JP-03", "JP-04", "SG-01", "SG-02"]

for node in nodes:
    # Switch to this node
    encoded = urllib.parse.quote("Polymarket")
    data = json.dumps({"name": node}).encode()
    req = urllib.request.Request(
        f"{MIHOMO_API}/proxies/{encoded}",
        data=data,
        method="PUT",
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"  {node}: Failed to switch - {e}")
        continue

    time.sleep(0.5)

    # Test exit IP and Polymarket access
    client = httpx.Client(proxy=PROXY, timeout=httpx.Timeout(10.0))
    try:
        r = client.get("https://api.ipify.org?format=json")
        ip_info = r.json()
        ip = ip_info.get("ip", "unknown")
    except Exception as e:
        ip = f"error: {e}"

    try:
        r2 = client.post(
            "https://clob.polymarket.com/order",
            json={},
            headers={"Content-Type": "application/json"},
        )
        pm_status = r2.status_code
        pm_body = r2.text[:80]
    except Exception as e:
        pm_status = "error"
        pm_body = str(e)[:80]

    client.close()

    # Status indicator
    if pm_status == 403:
        status = "BLOCKED"
    elif pm_status in [400, 401, 404]:
        status = "OK (API reachable)"  # 400/401/404 means not blocked by geo
    elif pm_status == 200:
        status = "OK"
    else:
        status = f"status={pm_status}"

    print(f"{node}: IP={ip}  PM={status}")

print("\nDone!")
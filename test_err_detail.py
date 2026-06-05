import httpx, json
proxy = "http://127.0.0.1:7890"
client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(15.0))

# Full error response from POST
headers = {"Content-Type": "application/json"}
try:
    r = client.post("https://clob.polymarket.com/order", headers=headers, json={})
    print(f"Status: {r.status_code}")
    print(f"Body: {r.text[:500]}")
    print(f"Response headers:")
    for k, v in dict(r.headers).items():
        if k.lower() in ['content-type', 'x-request-id', 'cf-ray', 'server']:
            print(f"  {k}: {v}")
except Exception as e:
    print(f"Error: {e}")

# Verify GET works
r2 = client.get("https://clob.polymarket.com/time")
print(f"\nGET /time: {r2.status_code} - {r2.text[:50]}")

# Check what IP the proxy is using (IP check)
try:
    r3 = client.get("https://api.ipify.org?format=json")
    print(f"Proxy IP: {r3.json()}")
except:
    print("IP check failed")

client.close()
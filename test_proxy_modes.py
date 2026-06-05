"""Test if mihomo rules correctly route Polymarket traffic through the US/JP group"""
import httpx

# Test SOCKS proxy
proxy_socks = "socks5://127.0.0.1:7891"
print(f"Testing SOCKS proxy: {proxy_socks}")
try:
    client = httpx.Client(proxy=proxy_socks, timeout=httpx.Timeout(15.0))
    r = client.get("https://api.ipify.org?format=json")
    print(f"Exit IP (SOCKS): {r.json()}")
    r2 = client.post("https://clob.polymarket.com/order", json={}, headers={"Content-Type": "application/json"})
    print(f"POST /order (SOCKS): {r2.status_code} - {r2.text[:200]}")
    client.close()
except Exception as e:
    print(f"SOCKS error: {e}")

# Try HTTP proxy
proxy_http = "http://127.0.0.1:7890"
print(f"\nTesting HTTP proxy: {proxy_http}")
try:
    client2 = httpx.Client(proxy=proxy_http, timeout=httpx.Timeout(15.0))
    r = client2.get("https://api.ipify.org?format=json")
    print(f"Exit IP (HTTP): {r.json()}")
    r2 = client2.post("https://clob.polymarket.com/order", json={}, headers={"Content-Type": "application/json"})
    print(f"POST /order (HTTP): {r2.status_code} - {r2.text[:200]}")
    client2.close()
except Exception as e:
    print(f"HTTP error: {e}")
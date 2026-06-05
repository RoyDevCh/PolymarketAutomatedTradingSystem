"""Direct proxy test for CLOB POST requests"""
import os, httpx, json
proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
print(f"Proxy: {proxy}")

# Create proxied client
client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True)

# Test POST to CLOB
print("Testing POST to CLOB...")
try:
    resp = client.post(
        "https://clob.polymarket.com/order",
        headers={"Content-Type": "application/json"},
        json={"test": "ping"},
    )
    print(f"POST status: {resp.status_code}")
    print(f"POST response: {resp.text[:300]}")
except Exception as e:
    print(f"POST error: {type(e).__name__}: {e}")

# Try GET to time endpoint
resp2 = client.get("https://clob.polymarket.com/time")
print(f"\nGET /time: {resp2.status_code} - {resp2.text[:50]}")

# Now test with proper auth headers through the py_clob_client
print("\nTesting via py_clob_client with proxy injection...")
sys_path = "."
import sys
sys.path.insert(0, sys_path)
from core.config import CONFIG
from core.clob_client import _inject_proxy_to_clob_client
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds

# Create client
c = ClobClient(
    host=CONFIG.clob.api_url,
    key=CONFIG.wallet.private_key,
    chain_id=137,
    creds=ApiCreds(
        api_key=CONFIG.clob.api_key,
        api_secret=CONFIG.clob.api_secret,
        api_passphrase=CONFIG.clob.api_passphrase,
    ),
)

# Inject proxy
_inject_proxy_to_clob_client()

# Test derive_api_key (uses GET, should work)
try:
    creds = c.derive_api_key()
    print(f"derive_api_key: OK - {creds.api_key[:12]}...")
except Exception as e:
    print(f"derive_api_key: {type(e).__name__}: {e}")

# Test get_markets (uses GET through client)
try:
    markets = c.get_markets()
    print(f"get_markets: OK - {len(markets)} markets")
except Exception as e:
    print(f"get_markets: {type(e).__name__}: {str(e)[:100]}")
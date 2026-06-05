"""Direct proxy test for CLOB post_order"""
import os, sys
sys.path.insert(0, ".")
from pathlib import Path
proxyrc = Path.home() / ".proxyrc"
if proxyrc.exists():
    for line in proxyrc.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" in line and not line.startswith("#"):
            key, _, val = line.partition("=")
            if key.strip().lower().endswith("_proxy"):
                os.environ.setdefault(key.strip(), val.strip())

PROXY = os.environ.get("https_proxy") or os.environ.get("http_proxy")
print(f"Proxy: {PROXY}")

import httpx
import py_clob_client.http_helpers.helpers as h

# Step 1: Create a new proxied httpx.Client and REPLACE the module-level one
print("\nStep 1: Replacing httpx.Client with proxied version...")
proxied_client = httpx.Client(
    proxy=PROXY,
    timeout=httpx.Timeout(30.0),
    follow_redirects=True,
)
h._http_client = proxied_client
print(f"Replaced: {type(h._http_client)} proxy={hasattr(h._http_client, '_proxy')}")

# Step 2: Test the GET request (should work)
print("\nStep 2: Testing GET /time...")
try:
    resp = h._http_client.get("https://clob.polymarket.com/time")
    print(f"GET /time: {resp.status_code} - {resp.text[:50]}")
except Exception as e:
    print(f"GET ERROR: {e}")

# Step 3: Test signing (should work offline)
from core.config import CONFIG
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs

print("\nStep 3: Creating ClobClient...")
client = ClobClient(
    host=CONFIG.clob.api_url,
    key=CONFIG.wallet.private_key,
    chain_id=137,
    creds=ApiCreds(
        api_key=CONFIG.clob.api_key,
        api_secret=CONFIG.clob.api_secret,
        api_passphrase=CONFIG.clob.api_passphrase,
    ),
)
print(f"Client created: host={client.host}")

# Step 4: Test post_order with a minimal order
print("\nStep 4: Testing post_order with minimal params...")
print(f"  Using proxy: {PROXY}")

# Use a cheap market token - Roland Garros
token_id = "26497910172462613720978711304407120308689418849705328618663286869271980885216"

order_args = OrderArgs(
    token_id=token_id,
    price=0.01,       # Far OTM - almost impossible to fill
    size=1.0,           # 1 share = $0.01
    side="BUY",
)

try:
    print("  Creating signed order...")
    signed_order = client.create_order(order_args)
    print(f"  Signed order created: {str(signed_order)[:80]}...")
    
    print("  Posting order through proxied client...")
    # The post_order uses h._http_client (which we replaced with proxied version)
    response = client.post_order(signed_order, "GTC")
    print(f"  [OK] Response: {response}")
    
except Exception as e:
    import traceback
    print(f"  [FAIL] {type(e).__name__}: {e}")
    # Check if the error is 403 region restriction
    if "403" in str(e) or "region" in str(e).lower():
        print("\n  ERROR: Polymarket is blocking requests from this region.")
        print("  This means the proxy is NOT being used by post_order().")
        print("  The proxy was injected but ClobClient may cache its own httpx.Client.")
        print("\n  Trying manual approach: direct HTTP POST through proxy...")
        
        # Manual approach: make the POST request ourselves through the proxy
        import json
        from py_clob_client.http_helpers.helpers import POST_ORDER
        from py_clob_client.order_builder.constants import AMOUNTS_IDS
        
        # Build headers manually
        body = client.create_order_body(signed_order, "GTC") if hasattr(client, 'create_order_body') else None
        
        # Try direct httpx post
        print("\n  Trying direct httpx.post through proxy...")
        url = f"{CONFIG.clob.api_url}{POST_ORDER}"
        headers = {
            "Content-Type": "application/json",
        }
        
        # Use the client's auth headers
        try:
            from py_clob_client.http_helpers.auth import create_level_2_headers
            from py_clob_client.http_helpers.auth import RequestArgs
            request_args = RequestArgs(
                method="POST",
                request_path=POST_ORDER,
                body=body if body else {},
            )
            auth_headers = create_level_2_headers(client.signer, client.creds, request_args)
            headers.update(auth_headers)
        except Exception as he:
            print(f"  Auth header creation skipped: {he}")

if __name__ == "__main__":
    pass
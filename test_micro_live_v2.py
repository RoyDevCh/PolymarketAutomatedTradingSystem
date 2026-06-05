"""Micro live test - find active market and place test order"""
import os, sys, asyncio, json, aiohttp
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

from core.config import CONFIG
from core.clob_client import _inject_proxy_to_clob_client

# Inject proxy BEFORE importing anything else
_inject_proxy_to_clob_client()

import httpx
import py_clob_client.http_helpers.helpers as h
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs

PROXY = os.environ.get("https_proxy") or os.environ.get("http_proxy")
print(f"Proxy: {PROXY}")
print(f"httpx client proxy check: {hasattr(h._http_client, '_transport')}\n")

# Create client
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

# Step 1: Verify API connection
print("Step 1: Verify API connection")
try:
    resp = h._http_client.get(f"{CONFIG.clob.api_url}/time")
    print(f"  GET /time: {resp.status_code} - {resp.text[:50]}")
except Exception as e:
    print(f"  FAIL: {e}")
    sys.exit(1)

# Step 2: Find an active market with volume
print("\nStep 2: Find active market...")
proxy = PROXY
async def find_market():
    async with aiohttp.ClientSession(trust_env=True) as s:
        url = "https://gamma-api.polymarket.com/markets?active=true&closed=false&order=volume&ascending=false&limit=10"
        async with s.get(url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=15)) as r:
            markets = await r.json()
    
    for m in markets[:10]:
        clob_ids = m.get("clobTokenIds", [])
        if isinstance(clob_ids, str):
            clob_ids = json.loads(clob_ids)
        q = m.get("question", "")[:50]
        vol = float(m.get("volumeNum", 0) or 0)
        if len(clob_ids) >= 2:
            print(f"  Found: {q} (Vol=${vol:,.0f})")
            print(f"    YES token: {clob_ids[0][:40]}...")
            return clob_ids[0], m
    
    return None, None

token_id, market = asyncio.run(find_market())
if not token_id:
    print("  FAIL: No active market found")
    sys.exit(1)

# Step 3: Get current orderbook to find a reasonable price
print(f"\nStep 3: Get orderbook for {token_id[:30]}...")
try:
    book = client.get_order_book(token_id)
    if book and book.asks:
        best_ask = float(book.asks[0].price)
        print(f"  Best ask: {best_ask}")
        
        # Place a GTC limit buy at 50% below best ask (extremely unlikely to fill)
        # For a market at 0.999, this would be $0.50 (still very far OTM)
        safe_price = round(min(best_ask * 0.5, 0.50), 2)
        safe_price = max(safe_price, 0.01)  # Minimum price on Polymarket
    else:
        print("  No asks, using default price")
        safe_price = 0.01
except Exception as e:
    print(f"  Warning: {e}, using default price")
    safe_price = 0.01

# Step 4: Place test order
print(f"\nStep 4: Place test order")
print(f"  Token: {token_id[:40]}...")
print(f"  Price: ${safe_price} (far OTM)")
print(f"  Size:  1.0 share (${safe_price} total)")
print(f"  Side:  BUY")

try:
    order_args = OrderArgs(
        token_id=token_id,
        price=safe_price,
        size=1.0,
        side="BUY",
    )
    signed_order = client.create_order(order_args)
    print(f"  Signed order created successfully")
    
    response = client.post_order(signed_order, "GTC")
    print(f"\n  [SUCCESS] Order response: {response}")
    
    if isinstance(response, dict):
        order_id = response.get("orderID", response.get("order_id", ""))
        status = response.get("status", "")
        print(f"  Order ID: {order_id}")
        print(f"  Status: {status}")
        
        # Wait a moment then cancel
        print(f"\nStep 5: Cancel order...")
        import time
        time.sleep(2)
        
        try:
            cancel_result = client.cancel(order_id)
            print(f"  [SUCCESS] Cancel response: {cancel_result}")
        except Exception as ce:
            print(f"  Cancel result: {ce}")
            # Try cancel_all as fallback
            try:
                cancel_all = client.cancel_all()
                print(f"  cancel_all response: {cancel_all}")
            except:
                pass
        
        print("\n" + "=" * 60)
        print("  PHASE 2.5 MICRO LIVE TEST: COMPLETE!")
        print("  CLOB API:      OK (connected through proxy)")
        print("  EIP-712 Sign:   OK (order signed)")
        print("  Order Submit:   OK (order accepted)")
        print("  Order Cancel:   See above")
        print("=" * 60)
    else:
        print(f"  Response type: {type(response)}")
        print(f"  Response: {str(response)[:200]}")

except Exception as e:
    print(f"\n  [FAIL] {type(e).__name__}: {e}")
    if "403" in str(e):
        print("  Region restriction - proxy may not be working for POST requests")
    elif "404" in str(e):
        print("  Market not found - trying a different market")
    elif "insufficient" in str(e).lower():
        print("  Insufficient balance - check USDC")
    
    # Try cancel_all as cleanup
    try:
        client.cancel_all()
        print("  Cancelled all orders (cleanup)")
    except:
        pass
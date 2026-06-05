"""Try order with signature_type=1 (POLY_PROXY) using V2 SDK.

Our wallet is a V1-migrated proxy wallet (0x4b34FA1D...), not a V2 deposit wallet.
For proxy wallets, we should use signature_type=1 (POLY_PROXY) with the proxy as funder.
"""
import os, sys
sys.path.insert(0, ".")
from pathlib import Path
proxy_rc = Path.home() / ".proxyrc"
if proxy_rc.exists():
    for line in proxy_rc.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" in line and not line.startswith("#"):
            key, _, val = line.partition("=")
            if key.strip().lower().endswith("_proxy") and val.strip():
                os.environ.setdefault(key.strip(), val.strip())

import httpx
import py_clob_client_v2.http_helpers.helpers as _v2h
proxy_url = os.environ.get("https_proxy") or os.environ.get("http_proxy")
if proxy_url:
    _v2h._http_client = httpx.Client(proxy=proxy_url, timeout=httpx.Timeout(30.0), follow_redirects=True)

from core.config import CONFIG
from py_clob_client_v2 import (
    ClobClient, ApiCreds, OrderArgs, OrderType,
    PartialCreateOrderOptions, SignatureTypeV2,
)

# Our wallet addresses
EOA = "0x43083C461fc9b875c97032f375bf8aef81681B8e"
PROXY = "0x4b34FA1Dc7047f03c63f04e7555B1dF6A94d2403"  # V1 proxy wallet from getSafeWalletAddress

cfg = CONFIG.clob
wallet_cfg = CONFIG.wallet

print("=" * 60)
print("  V2 Order Test - POLY_PROXY (sig_type=1)")
print("=" * 60)

# Try signature_type=1 (POLY_PROXY) with the proxy as funder
print("\n[1/3] Creating client with POLY_PROXY...")
api_creds = ApiCreds(
    api_key=cfg.api_key,
    api_secret=cfg.api_secret,
    api_passphrase=cfg.api_passphrase,
)

client = ClobClient(
    host=cfg.api_url,
    chain_id=wallet_cfg.chain_id,
    key=wallet_cfg.private_key,
    creds=api_creds,
    signature_type=SignatureTypeV2.POLY_PROXY,  # sig_type=1
    funder=PROXY,
)
print(f"  Signer: {client.signer.address()}")
print(f"  Builder funder: {client.builder.funder}")
print(f"  Builder sig_type: {client.builder.signature_type}")

# Find a market
print("\n[2/3] Finding active market...")
import aiohttp, json, asyncio

async def find_market():
    proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
    url = "https://gamma-api.polymarket.com/markets?active=true&closed=false&order=volume&ascending=false&limit=5"
    async with aiohttp.ClientSession(trust_env=True) as s:
        async with s.get(url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=15)) as r:
            return await r.json()

markets = asyncio.run(find_market())
token_id = condition_id = None
neg_risk = False

for m in markets[:5]:
    clob_ids = m.get("clobTokenIds", [])
    if isinstance(clob_ids, str):
        clob_ids = json.loads(clob_ids)
    if len(clob_ids) >= 2:
        token_id = clob_ids[0]
        condition_id = m.get("conditionId", "") or m.get("condition_id", "")
        neg_risk = m.get("negRisk", m.get("neg_risk", False))
        if isinstance(neg_risk, str):
            neg_risk = neg_risk.lower() == "true"
        question = m.get("question", "")[:60]
        print(f"  Market: {question}")
        print(f"  Token: {token_id[:40]}...")
        print(f"  NegRisk: {neg_risk}")
        break

if not token_id:
    print("  [FAIL] No market found")
    sys.exit(1)

# Place test order
print("\n[3/3] Placing test order with POLY_PROXY...")

# Get tick size
tick_size_str = "0.01"
min_size = 5.0
try:
    info = client.get_clob_market_info(condition_id)
    mts = info.get("mts", "0.01")
    mos = info.get("mos", "5")
    tick_size_str = str(mts) if isinstance(mts, str) else str(mts)
    min_size = float(mos) if isinstance(mos, (int, float)) else float(str(mos))
    print(f"  Tick: {tick_size_str}, Min: {min_size}")
except Exception as e:
    print(f"  Market info error: {e}")

safe_price = float(tick_size_str)
order_size = max(min_size, 1.0)

print(f"  Price: ${safe_price}")
print(f"  Size: {order_size}")
print(f"  Side: BUY")
print(f"  TickSize: {tick_size_str}")
print(f"  NegRisk: {neg_risk}")

try:
    order_args = OrderArgs(
        token_id=token_id,
        price=safe_price,
        size=order_size,
        side="BUY",
    )
    
    for ts in [tick_size_str, "0.01", "0.001"]:
        try:
            options = PartialCreateOrderOptions(tick_size=ts, neg_risk=bool(neg_risk))
            print(f"\n  Signing order (tick_size={ts}, neg_risk={neg_risk})...")
            signed_order = client.create_order(order_args, options)
            maker = getattr(signed_order, "maker", "?")
            signer = getattr(signed_order, "signer", "?")
            print(f"  [OK] Signed! Maker={maker}, Signer={signer}")
            break
        except KeyError as ke:
            print(f"  KeyError({ke}) with tick_size={ts}")
            continue
        except Exception as e:
            err_str = str(e)
            print(f"  Error: {type(e).__name__}: {err_str[:100]}")
            if "invalid price" in err_str.lower():
                safe_price = max(float(ts), safe_price)
                order_args = OrderArgs(token_id=token_id, price=safe_price, size=order_size, side="BUY")
                continue

    print(f"\n  Posting order...")
    response = client.post_order(signed_order, OrderType.GTC)
    print(f"\n  *** RESPONSE: {response}")

    if isinstance(response, dict):
        order_id = response.get("orderID", response.get("order_id", ""))
        status = response.get("status", "Unknown")
        print(f"  [OK] Order ID: {order_id}")
        print(f"  [OK] Status: {status}")

        # Cancel
        import time
        time.sleep(2)
        try:
            client.cancel_all()
            print(f"  [OK] Cancelled all orders")
        except Exception as e:
            print(f"  [WARN] Cancel: {e}")

except Exception as e:
    print(f"\n  [FAIL] {type(e).__name__}: {e}")
    try:
        client.cancel_all()
    except:
        pass
"""CLOB V2 Order Test with Deposit Wallet (POLY_1271)

Key insight: Polymarket V2 requires signature_type=3 (POLY_1271) with the
deposit wallet (proxy) address as the funder.
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
    print(f"[PROXY] {proxy_url[:30]}...")

from core.config import CONFIG
from py_clob_client_v2 import (
    ClobClient, ApiCreds, OrderArgs, OrderType,
    PartialCreateOrderOptions, SignatureTypeV2,
)

# Our wallet addresses
EOA = "0x43083C461fc9b875c97032f375bf8aef81681B8e"
FUNDER = "0x4b34FA1Dc7047f03c63f04e7555B1dF6A94d2403"  # Proxy wallet from V2 Exchange

cfg = CONFIG.clob
wallet_cfg = CONFIG.wallet

print("=" * 60)
print("  CLOB V2 Deposit Wallet Order Test (POLY_1271)")
print("=" * 60)

# Step 1: Create V2 Client with signature_type=3 (POLY_1271)
print("\n[1/5] Creating V2 Client with POLY_1271...")
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
    signature_type=SignatureTypeV2.POLY_1271,  # V2 deposit wallet flow
    funder=FUNDER,
)
print(f"  [OK] Client created with sig_type=POLY_1271, funder={FUNDER}")

# Step 2: Check balance
print("\n[2/5] Checking pUSD balance...")
try:
    from py_clob_client_v2 import BalanceAllowanceParams, AssetType
    bal = client.get_balance_allowance(params=BalanceAllowanceParams(
        asset_type=AssetType.COLLATERAL
    ))
    print(f"  [OK] Collateral balance: {bal}")
except Exception as e:
    print(f"  [WARN] Balance query: {e}")

# Step 3: Find market
print("\n[3/5] Finding active market...")
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
tick_size_str = "0.01"

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
        print(f"  [OK] {question}")
        print(f"       Token: {token_id[:40]}...")
        print(f"       NegRisk: {neg_risk}")
        break

if not token_id:
    print("  [FAIL] No market found")
    sys.exit(1)

# Step 4: Get market info
print("\n[4/5] Getting market info...")
try:
    info = client.get_clob_market_info(condition_id)
    mts = info.get("mts", "0.01")
    mos = info.get("mos", "5")
    tick_size_str = str(mts) if isinstance(mts, str) else f"{mts}"
    min_size = float(mos) if isinstance(mos, (int, float)) else float(str(mos))
    print(f"  Tick size: {tick_size_str}, Min size: {min_size}")
    print(f"  Market info: {info}")
except Exception as e:
    print(f"  [WARN] Market info: {e}")
    min_size = 5.0

# Step 5: Place order
print("\n[5/5] Placing test order...")
safe_price = 0.01  # Far OTM price

print(f"  Token: {token_id[:40]}...")
print(f"  Price: ${safe_price}")
print(f"  Size: {min_size}")
print(f"  Tick: {tick_size_str}")
print(f"  NegRisk: {neg_risk}")

try:
    order_args = OrderArgs(
        token_id=token_id,
        price=safe_price,
        size=max(min_size, 1.0),
        side="BUY",
    )

    # Try with correct tick_size
    for ts in [tick_size_str, "0.01", "0.1", "0.001", "0.0001"]:
        try:
            options = PartialCreateOrderOptions(
                tick_size=ts,
                neg_risk=bool(neg_risk),
            )
            print(f"\n  Creating order (tick_size={ts}, neg_risk={neg_risk})...")
            signed_order = client.create_order(order_args, options)
            print(f"  [OK] Order signed!")
            print(f"       Salt: {getattr(signed_order, 'salt', 'N/A')}")
            print(f"       Timestamp: {getattr(signed_order, 'timestamp', 'N/A')}")
            print(f"       Maker: {getattr(signed_order, 'maker', 'N/A')}")
            print(f"       Signer: {getattr(signed_order, 'signer', 'N/A')}")
            sig = getattr(signed_order, 'signature', '')
            if sig:
                print(f"       Sig: {sig[:30]}...")
            break
        except KeyError as ke:
            print(f"  KeyError({ke}) with tick_size={ts}")
            continue
        except Exception as e:
            print(f"  Error with tick_size={ts}: {type(e).__name__}: {e}")
            if "invalid price" in str(e).lower():
                safe_price = float(ts)
                order_args = OrderArgs(
                    token_id=token_id,
                    price=safe_price,
                    size=max(min_size, 1.0),
                    side="BUY",
                )
                continue
    else:
        print("  [FAIL] Could not sign order with any tick_size")
        sys.exit(1)

    # Post the order
    print(f"\n  *** Posting order to Polymarket CLOB V2 ***")
    response = client.post_order(signed_order, OrderType.GTC)
    print(f"\n  *** RESPONSE: {response}")

    if isinstance(response, dict):
        order_id = response.get("orderID", response.get("order_id", ""))
        status = response.get("status", "Unknown")
        print(f"  [OK] Order ID: {order_id}")
        print(f"  [OK] Status: {status}")

        # Wait and cancel
        import time
        print("\n  Waiting 3 seconds...")
        time.sleep(3)

        # Cancel
        if order_id:
            try:
                cancel_result = client.cancel(order_id)
                print(f"  [OK] Cancel: {cancel_result}")
            except Exception as e:
                print(f"  [WARN] Cancel: {e}")

        try:
            cancel_all = client.cancel_all()
            print(f"  [OK] Cancel all: {cancel_all}")
        except Exception as e:
            print(f"  [WARN] Cancel all: {e}")

        # Summary
        print("\n" + "=" * 60)
        print("  PHASE 2.5 - DEPOSIT WALNEL FLOW - COMPLETE!")
        print("=" * 60)
        print(f"  Proxy (Funder): {FUNDER}")
        print(f"  Order Signed:   OK (POLY_1271)")
        print(f"  Order Posted:   OK")
        print(f"  Order ID:       {order_id}")
        print()
        print("  ========== V2 ORDER PIPELINE VERIFIED! ==========")

    elif isinstance(response, str):
        print(f"  [OK] Response: {response}")

except Exception as e:
    print(f"\n  [FAIL] {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    try:
        client.cancel_all()
    except:
        pass
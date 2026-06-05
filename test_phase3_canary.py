"""
Phase 3 Canary Test
- Verify core ClobClient v2 integration
- Test asyncio.gather dual-leg order submission
- Uses far-OTM prices to avoid fills
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")

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

from core.config import CONFIG, validate_config
from core.clob_client import get_clob_client, ClobClientManager
from py_clob_client_v2.clob_types import OrderArgs, OrderType, BalanceAllowanceParams, AssetType

print("=" * 60)
print("Phase 3 Canary Test")
print("=" * 60)

errors = validate_config(CONFIG)
if errors:
    print("Config errors:", errors)
    sys.exit(1)

print(f"Deposit: {CONFIG.wallet.deposit_wallet}")
print(f"SigType: {CONFIG.wallet.signature_type}")
print(f"Max trade: ${CONFIG.trading.max_trade_size}")

ClobClientManager.reset()
client = get_clob_client()

params = BalanceAllowanceParams(
    asset_type=AssetType.COLLATERAL,
    signature_type=CONFIG.wallet.signature_type,
)
client.update_balance_allowance(params)
bal = client.get_balance_allowance(params)
balance_usd = int(bal.get("balance", "0")) / 1e6
print(f"CLOB balance: ${balance_usd:.2f}")

if balance_usd < 5:
    print("FAIL: balance too low for canary test")
    sys.exit(1)

import httpx
proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
hc = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True) if proxy else httpx.Client(timeout=30.0)
markets = hc.get(
    "https://gamma-api.polymarket.com/markets",
    params={"limit": 10, "active": "true", "closed": "false", "order": "volume", "ascending": "false"},
).json()

token_yes = token_no = None
question = ""
for m in markets:
    ids = json.loads(m["clobTokenIds"]) if isinstance(m.get("clobTokenIds"), str) else m.get("clobTokenIds", [])
    if len(ids) >= 2:
        token_yes, token_no = ids[0], ids[1]
        question = m.get("question", "")[:60]
        break

if not token_yes:
    print("FAIL: no market found")
    sys.exit(1)

print(f"Market: {question}")
print(f"YES: {token_yes[:30]}...")
print(f"NO:  {token_no[:30]}...")

# Far OTM: price=0.01, size=5 (min), cost ~$0.05 per leg
PRICE, SIZE = 0.01, 5.0


async def place_leg(token_id: str, label: str):
    t0 = time.time()
    args = OrderArgs(price=PRICE, size=SIZE, side="BUY", token_id=token_id)
    signed = await asyncio.to_thread(client.create_order, args)
    resp = await asyncio.to_thread(client.post_order, signed, OrderType.GTC)
    elapsed = (time.time() - t0) * 1000
    oid = resp.get("orderID", "") if isinstance(resp, dict) else ""
    ok = isinstance(resp, dict) and resp.get("success")
    print(f"  {label}: {'OK' if ok else 'FAIL'} order={oid[:20]}... {elapsed:.0f}ms")
    return oid, ok


async def main():
    print("\n--- Dual-leg asyncio.gather ---")
    t0 = time.time()
    results = await asyncio.gather(
        place_leg(token_yes, "YES"),
        place_leg(token_no, "NO"),
        return_exceptions=True,
    )
    total_ms = (time.time() - t0) * 1000
    print(f"  Total gather time: {total_ms:.0f}ms")

    order_ids = []
    for r in results:
        if isinstance(r, Exception):
            print(f"  LEG ERROR: {r}")
        elif r[1]:
            order_ids.append(r[0])

    if order_ids:
        print(f"\nCancelling {len(order_ids)} test orders...")
        cancel = client.cancel_orders(order_ids)
        print(f"  Cancel: {cancel}")

    if len(order_ids) == 2 and total_ms < 2000:
        print("\n" + "=" * 60)
        print("  PHASE 3 CANARY: PASS")
        print("  - CLOB v2 client OK")
        print("  - Dual-leg gather OK")
        print(f"  - Gather latency: {total_ms:.0f}ms")
        print("=" * 60)
    else:
        print("\nPHASE 3 CANARY: PARTIAL (check leg errors above)")
        sys.exit(1)


asyncio.run(main())

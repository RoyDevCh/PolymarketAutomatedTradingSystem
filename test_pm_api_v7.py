"""
Phase 2.5 - Test with Polymarket website API credentials.

Polymarket auth (docs):
  L1: EIP-712 sign with private key (create/derive API key)
  L2: HMAC with API_KEY + API_SECRET + API_PASSPHRASE

V2 deposit wallet flow:
  signature_type=2 (POLY_NETWORK): maker=funder, signer=EOA
  signature_type=3 (POLY_1271): maker=funder, signer must match API key address
  funder = on-chain deposit/proxy wallet holding USDC
"""
import os
import sys
import json
from pathlib import Path

sys.path.insert(0, ".")

# Load proxy
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

# Load .env
env_path = Path("/home/roy/polymarket-arb/.env")
for line in env_path.read_text().splitlines():
    line = line.strip()
    if line.startswith("#") or not line or "=" not in line:
        continue
    key, _, val = line.partition("=")
    os.environ.setdefault(key.strip(), val.strip())

import httpx
import py_clob_client_v2.http_helpers.helpers as _v2h
from eth_account import Account

proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
if proxy:
    _v2h._http_client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True)

from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import ApiCreds, OrderArgs, OrderType, AssetType, BalanceAllowanceParams

# Addresses
EOA = Account.from_key(os.environ["PRIVATE_KEY"]).address
PM_API_ADDR = os.environ.get("PM_API_ADDRESS", "0x6b1fda796ffdd756d06cf20ce43f3c8a172e60ee")
DEPOSIT_WALLET = os.environ.get("DEPOSIT_WALLET", "0xAe886C5740F6614e0300BC2AF95e730f150685Ff")

api_key = os.environ.get("PM_API_KEY") or os.environ.get("API_KEY", "")
api_secret = os.environ.get("PM_API_SECRET") or os.environ.get("API_SECRET", "")
api_passphrase = os.environ.get("PM_API_PASSPHRASE") or os.environ.get("API_PASSPHRASE", "")

print("=" * 60)
print("Phase 2.5 Micro Live Test v7 (Polymarket API)")
print("=" * 60)
print(f"EOA (our key):     {EOA}")
print(f"PM API address:    {PM_API_ADDR}")
print(f"Deposit wallet:    {DEPOSIT_WALLET}")
print(f"API Key:           {api_key[:20]}..." if api_key else "API Key: MISSING")
print(f"API Secret:        {'SET' if api_secret else 'MISSING'}")
print(f"API Passphrase:    {'SET' if api_passphrase else 'MISSING'}")
print(f"Proxy:             {proxy or 'none'}")

if not all([api_key, api_secret, api_passphrase]):
    print("\n[FAIL] Need API_KEY, API_SECRET, API_PASSPHRASE in .env")
    print("Set PM_API_KEY / PM_API_SECRET / PM_API_PASSPHRASE for website credentials")
    sys.exit(1)

api_creds = ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase)

# Test configurations: (sig_type, funder, description)
configs = [
    (2, DEPOSIT_WALLET, "POLY_NETWORK + deposit wallet funder"),
    (2, PM_API_ADDR, "POLY_NETWORK + PM API addr as funder"),
    (3, DEPOSIT_WALLET, "POLY_1271 + deposit wallet funder"),
]

# Step 1: Check balance with each config
print("\n--- Step 1: Query pUSD/Collateral Balance ---")
for sig_type, funder, desc in configs:
    try:
        client = ClobClient(
            host="https://clob.polymarket.com",
            key=os.environ["PRIVATE_KEY"],
            chain_id=137,
            creds=api_creds,
            signature_type=sig_type,
            funder=funder,
        )
        if proxy:
            _v2h._http_client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True)

        bal = client.get_balance_allowance(params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        print(f"  sig={sig_type} funder={funder[:10]}...: {bal}")
    except Exception as e:
        print(f"  sig={sig_type} funder={funder[:10]}...: ERROR {type(e).__name__}: {str(e)[:120]}")

# Step 2: Find market and try order
print("\n--- Step 2: Place Test Order ---")
http_client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True) if proxy else httpx.Client(timeout=httpx.Timeout(30.0))
resp = http_client.get(
    "https://gamma-api.polymarket.com/markets",
    params={"limit": 5, "active": "true", "closed": "false", "order": "volume", "ascending": "false"},
)
markets = resp.json()
m = markets[0]
clob_ids = m.get("clobTokenIds", [])
if isinstance(clob_ids, str):
    clob_ids = json.loads(clob_ids)
yes_token = clob_ids[0]
print(f"Market: {m.get('question', '?')[:60]}")
print(f"Token:  {yes_token[:40]}...")

for sig_type, funder, desc in configs:
    print(f"\n  Trying: {desc}")
    try:
        client = ClobClient(
            host="https://clob.polymarket.com",
            key=os.environ["PRIVATE_KEY"],
            chain_id=137,
            creds=api_creds,
            signature_type=sig_type,
            funder=funder,
        )
        if proxy:
            _v2h._http_client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True)

        order_args = OrderArgs(price=0.01, size=1.0, side="BUY", token_id=yes_token)
        signed = client.create_order(order_args)
        print(f"    Signed: {type(signed).__name__}")

        result = client.post_order(signed, OrderType.GTC)
        print(f"    *** ORDER SUCCESS: {result} ***")
        order_id = result.get("orderID", result.get("order_id", "")) if isinstance(result, dict) else str(result)
        if order_id:
            print(f"    Order ID: {order_id}")
            try:
                client.cancel(order_id)
                print(f"    Cancelled: {order_id}")
            except Exception as ce:
                print(f"    Cancel warn: {ce}")
        break
    except Exception as e:
        err = str(e)
        print(f"    FAIL: {type(e).__name__}: {err[:200]}")

print("\n--- Done ---")

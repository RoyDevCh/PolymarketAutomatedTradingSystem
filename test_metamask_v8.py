"""Phase 2.5: MetaMask login flow - derive CLOB creds + test order."""
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

# Load env
env_path = Path("/home/roy/polymarket-arb/.env")
for line in env_path.read_text().splitlines():
    line = line.strip()
    if line.startswith("#") or not line or "=" not in line:
        continue
    key, _, val = line.partition("=")
    os.environ.setdefault(key.strip(), val.strip())

from eth_account import Account
from web3 import Web3

DEPOSIT_WALLET = os.environ.get("DEPOSIT_WALLET", "0x181242c978fb34c26068f8B154126F8Ea745C88B")
BUILDER_CODE = os.environ.get("BUILDER_CODE", "")

pk = os.environ["PRIVATE_KEY"]
eoa = Account.from_key(pk).address

print("=" * 60)
print("MetaMask Flow Test v8")
print("=" * 60)
print(f"EOA (signer):     {eoa}")
print(f"Deposit wallet:   {DEPOSIT_WALLET}")
print(f"Builder code:     {BUILDER_CODE[:20]}..." if BUILDER_CODE else "Builder code:     (none)")

# Check on-chain status
w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
USDC = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
erc20_abi = [{"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf",
              "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}]
usdc = w3.eth.contract(address=USDC, abi=erc20_abi)

for name, addr in [("EOA", eoa), ("Deposit", DEPOSIT_WALLET)]:
    ca = Web3.to_checksum_address(addr)
    code = w3.eth.get_code(ca)
    matic = w3.from_wei(w3.eth.get_balance(ca), "ether")
    usdc_bal = usdc.functions.balanceOf(ca).call() / 1e6
    status = "DEPLOYED" if len(code) > 0 else "EOA/NOT_DEPLOYED"
    print(f"  {name}: MATIC={matic:.4f}, USDC={usdc_bal:.2f}, code={len(code)} ({status})")

import httpx
import py_clob_client_v2.http_helpers.helpers as _v2h

proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
if proxy:
    _v2h._http_client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True)
    print(f"Proxy: {proxy}")

from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import ApiCreds, OrderArgs, OrderType

# Step 1: Derive CLOB API key via L1 (Quickstart flow)
print("\n--- Step 1: Derive CLOB API Key (L1) ---")
l1_client = ClobClient(
    host="https://clob.polymarket.com",
    key=pk,
    chain_id=137,
    signature_type=2,
    funder=DEPOSIT_WALLET,
)
if proxy:
    _v2h._http_client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True)

try:
    creds = l1_client.derive_api_key()
    print(f"Derived API Key: {creds.api_key}")
    print(f"Secret: {creds.api_secret[:12]}...")
    print(f"Passphrase: {creds.api_passphrase[:12]}...")
except Exception as e:
    print(f"derive_api_key failed: {e}")
    print("Trying create_api_key()...")
    creds = l1_client.create_api_key()
    print(f"Created API Key: {creds.api_key}")

# Step 2: Full client with derived creds
print("\n--- Step 2: CLOB Balance Check ---")
client = ClobClient(
    host="https://clob.polymarket.com",
    key=pk,
    chain_id=137,
    creds=creds,
    signature_type=2,
    funder=DEPOSIT_WALLET,
)
if proxy:
    _v2h._http_client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True)

try:
    balance = client.get_balance_allowance()
    print(f"Balance/Allowance: {balance}")
except Exception as e:
    print(f"Balance error: {type(e).__name__}: {str(e)[:200]}")

# Step 3: Find market and place micro order
print("\n--- Step 3: Micro Order Test ---")
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
print(f"Token: {yes_token[:30]}...")

order_args = OrderArgs(price=0.50, size=1.0, side="BUY", token_id=yes_token)
try:
    signed = client.create_order(order_args)
    print(f"Order signed: {type(signed).__name__}")
    result = client.post_order(signed, OrderType.GTC)
    print(f"Order result: {result}")
    if isinstance(result, dict):
        oid = result.get("orderID") or result.get("order_id") or result.get("id")
        if oid:
            print(f"\n*** ORDER PLACED: {oid} ***")
except Exception as e:
    err = str(e)
    print(f"Order error: {type(e).__name__}")
    print(f"  {err[:300]}")
    if hasattr(e, "status_code"):
        print(f"  Status: {e.status_code}")

print("\n--- Done ---")
print(f"\nUpdate .env with derived credentials:")
print(f"API_KEY={creds.api_key}")
print(f"API_SECRET={creds.api_secret}")
print(f"API_PASSPHRASE={creds.api_passphrase}")
print(f"DEPOSIT_WALLET={DEPOSIT_WALLET}")
print(f"WALLET_ADDRESS={eoa}")

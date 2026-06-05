"""Test order with signature_type=2 and funder=deposit_wallet."""
import os, sys, json
sys.path.insert(0, ".")
from pathlib import Path
from eth_account import Account
from web3 import Web3

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

pk = os.environ["PRIVATE_KEY"]
addr = Account.from_key(pk).address
DEPOSIT_WALLET = "0xAe886C5740F6614e0300BC2AF95e730f150685Ff"

print(f"EOA: {addr}")
print(f"Deposit Wallet: {DEPOSIT_WALLET}")

# Verify deposit wallet is deployed
w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
code = w3.eth.get_code(Web3.to_checksum_address(DEPOSIT_WALLET))
print(f"Deposit Wallet code: {len(code)} bytes ({'DEPLOYED' if len(code) > 0 else 'NOT DEPLOYED'})")

import httpx
import py_clob_client_v2.http_helpers.helpers as _v2h
proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
if proxy:
    _v2h._http_client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True)

from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import ApiCreds, OrderArgs, OrderType

api_key = os.environ["API_KEY"]
api_secret = os.environ["API_SECRET"]
api_passphrase = os.environ["API_PASSPHRASE"]

api_creds = ApiCreds(
    api_key=api_key,
    api_secret=api_secret,
    api_passphrase=api_passphrase,
)

# Test both signature_type=2 (POLY_NETWORK) and signature_type=3 (POLY_1271)
for sig_type, sig_name in [(2, "POLY_NETWORK"), (3, "POLY_1271")]:
    print(f"\n{'='*60}")
    print(f"  Testing with signature_type={sig_type} ({sig_name})")
    print(f"  funder={DEPOSIT_WALLET}")
    print(f"{'='*60}")
    
    try:
        client = ClobClient(
            host="https://clob.polymarket.com",
            key=pk,
            chain_id=137,
            creds=api_creds,
            signature_type=sig_type,
            funder=DEPOSIT_WALLET,
        )
        # Re-inject proxy
        if proxy:
            _v2h._http_client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True)
        
        # Get a market
        http_client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True) if proxy else httpx.Client(timeout=httpx.Timeout(30.0))
        resp = http_client.get(
            "https://gamma-api.polymarket.com/markets",
            params={"limit": 5, "active": "true", "closed": "false", "order": "volume", "ascending": "false"},
        )
        markets = resp.json()
        
        if not markets:
            print("No markets found!")
            continue
        
        m = markets[0]
        clob_ids = m.get("clobTokenIds", [])
        if isinstance(clob_ids, str):
            clob_ids = json.loads(clob_ids)
        yes_token = clob_ids[0] if len(clob_ids) > 0 else None
        print(f"Market: {m.get('question', '?')[:60]}")
        print(f"YES token: {yes_token[:30]}..." if yes_token else "No YES token!")
        
        if not yes_token:
            continue
        
        # Try to create and post an order
        order_args = OrderArgs(
            price=0.50,
            size=1.0,
            side="BUY",
            token_id=yes_token,
        )
        
        signed_order = client.create_order(order_args)
        print(f"Order signed: {type(signed_order).__name__}")
        
        # Post the order
        result = client.post_order(signed_order, OrderType.GTC)
        print(f"Order result: {result}")
        
        if isinstance(result, dict):
            order_id = result.get("orderID", result.get("order_id", result.get("id", "")))
            if order_id:
                print(f"\n  *** ORDER PLACED SUCCESSFULLY! ***")
                print(f"  Order ID: {order_id}")
                break  # Success!
        else:
            print(f"  Result: {result}")
            
    except Exception as e:
        err = str(e)
        print(f"Error: {type(e).__name__}")
        if "geoblock" in err.lower() or "restricted" in err.lower():
            print(f"  GEOBLOCKED: {err[:200]}")
        elif "not allowed" in err.lower() or "maker address" in err.lower():
            print(f"  Address not allowed: {err[:200]}")
        elif "signature" in err.lower() or "signer" in err.lower():
            print(f"  Signature error: {err[:200]}")
        elif "deposit" in err.lower() or "funder" in err.lower():
            print(f"  Deposit/funder issue: {err[:200]}")
        elif "insufficient" in err.lower() or "balance" in err.lower():
            print(f"  Insufficient balance: {err[:200]}")
        else:
            print(f"  Error: {err[:200]}")
        
        if hasattr(e, 'status_code'):
            print(f"  Status code: {e.status_code}")

print(f"\nDone!")
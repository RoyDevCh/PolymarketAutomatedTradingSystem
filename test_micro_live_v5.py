"""Phase 2.5 Micro Live Test v5 - Fixed token ID extraction."""
import os, sys, time, json
sys.path.insert(0, ".")
from pathlib import Path

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

# Load deposit wallet
new_env = Path("/home/roy/polymarket-arb/wallet_new.env")
for line in new_env.read_text().splitlines():
    line = line.strip()
    if line.startswith("#") or not line or "=" not in line:
        continue
    key, _, val = line.partition("=")
    if key.strip() == "DEPOSIT_WALLET":
        DEPOSIT_WALLET = val.strip()

from eth_account import Account
from web3 import Web3

pk = os.environ.get("PRIVATE_KEY", "")
addr = Account.from_key(pk).address
print(f"=" * 60)
print(f"  Phase 2.5 Micro Live Test v5")
print(f"=" * 60)
print(f"Wallet: {addr}")

# Check deposit wallet status
w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
deposit_code = w3.eth.get_code(Web3.to_checksum_address(DEPOSIT_WALLET))
print(f"Deposit Wallet: {DEPOSIT_WALLET} ({'DEPLOYED' if len(deposit_code) > 0 else 'NOT DEPLOYED'})")

# Create V2 client with proxy
import httpx
import py_clob_client_v2.http_helpers.helpers as _v2h
proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
if proxy:
    _v2h._http_client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True)
    print(f"Proxy: {proxy}")

from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import OrderArgs, OrderType

api_key = os.environ.get("API_KEY", "")
api_secret = os.environ.get("API_SECRET", "")
api_passphrase = os.environ.get("API_PASSPHRASE", "")

print(f"\n--- Creating V2 CLOB Client ---")
client = ClobClient(host="https://clob.polymarket.com", key=pk, chain_id=137)
client.api_key = api_key
client.api_secret = api_secret
client.api_passphrase = api_passphrase
# Re-inject proxy after client creation
if proxy:
    _v2h._http_client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True)

# Get markets and find one with valid token IDs
print(f"\n--- Finding Active Market ---")
markets = client.get_markets()
if isinstance(markets, dict):
    markets = markets.get("data", [])
print(f"Got {len(markets)} markets")

target_market = None
for m in markets:
    # Look for active markets with good volume
    active = m.get("active", True)
    closed = m.get("closed", False)
    vol = m.get("volumeNum", 0)
    if isinstance(vol, str):
        try:
            vol = float(vol)
        except:
            vol = 0
    vol = float(vol) if vol else 0
    
    if not closed and active and vol > 1000:
        target_market = m
        break

if not target_market:
    # Fallback: just pick first non-closed market
    for m in markets[:20]:
        if not m.get("closed", False):
            target_market = m
            break

if not target_market:
    print("No suitable market found! Using first market.")
    target_market = markets[0]

q = target_market.get("question", "?")[:80]
condition_id = target_market.get("conditionId", "")
tokens = target_market.get("tokens", [])
volume = target_market.get("volumeNum", 0)
print(f"Market: {q}")
print(f"Volume: {volume}")
print(f"Condition ID: {condition_id}")
print(f"Tokens: {json.dumps(tokens, indent=2)[:500]}")

# Extract token IDs properly
yes_token = None
no_token = None
for t in tokens:
    token_id = t.get("token_id", "")
    outcome = t.get("outcome", "").lower()
    price = t.get("price", 0)
    print(f"  Token: outcome={outcome}, id={token_id[:30]}..., price={price}")
    if outcome == "yes":
        yes_token = token_id
    elif outcome == "no":
        no_token = token_id

if not yes_token and tokens:
    # Fallback: use first token
    yes_token = tokens[0].get("token_id", "")
    print(f"  Using first token as YES: {yes_token[:30]}...")

if not yes_token:
    print("ERROR: No token ID found! Trying raw API...")
    # Try getting the token ID from the market data directly
    clob_token_ids_str = target_market.get("clobTokenIds", "")
    if clob_token_ids_str:
        try:
            clob_token_ids = json.loads(clob_token_ids_str) if isinstance(clob_token_ids_str, str) else clob_token_ids_str
            yes_token = clob_token_ids[0] if len(clob_token_ids) > 0 else None
            print(f"  From clobTokenIds: {yes_token[:30] if yes_token else 'None'}...")
        except:
            pass

if not yes_token:
    print("ERROR: Cannot find token ID. Dumping market data...")
    print(json.dumps(target_market, indent=2)[:1000])
    sys.exit(1)

print(f"\nSelected YES token: {yes_token}")

# Get orderbook
print(f"\n--- Getting Orderbook ---")
try:
    book = client.get_order_book(yes_token)
    bids = book.get("bids", [])
    asks = book.get("asks", [])
    print(f"Bids: {len(bids)}, Asks: {len(asks)}")
    if bids:
        print(f"  Best bid: price={bids[0].get('price', 'N/A')}, size={bids[0].get('size', 'N/A')}")
    if asks:
        print(f"  Best ask: price={asks[0].get('price', 'N/A')}, size={asks[0].get('size', 'N/A')}")
except Exception as e:
    print(f"Orderbook error: {type(e).__name__}: {str(e)[:200]}")

# Try to place buy order
print(f"\n--- Attempting BUY Order ---")
print(f"Token: {yes_token[:30]}...")
print(f"Price: 0.50, Size: 1.0 (approx $0.50)")

try:
    order_args = OrderArgs(
        price=0.50,
        size=1.0,
        side="BUY",
        token_id=yes_token,
    )
    signed_order = client.create_order(order_args)
    print(f"Order signed: {type(signed_order).__name__}")
    
    # Try to post the order
    result = client.post_order(signed_order, OrderType.GTC)
    print(f"Order result: {result}")
    print(f"\n✅ ORDER PLACED SUCCESSFULLY!")
    
except Exception as e:
    err_str = str(e)
    print(f"Order error: {type(e).__name__}")
    
    if "geoblock" in err_str.lower() or "restricted" in err_str.lower():
        print(f"❌ GEOBLOCKED: {err_str[:300]}")
    elif "not allowed" in err_str.lower() or "maker address" in err_str.lower():
        print(f"❌ Address not allowed: {err_str[:300]}")
    elif "deposit" in err_str.lower():
        print(f"❌ Deposit wallet issue: {err_str[:300]}")
    elif "Invalid token" in err_str:
        print(f"❌ Invalid token ID format: {err_str[:300]}")
        # Try with the hex format instead
        print(f"\nTrying with raw token ID format...")
    elif "insufficient" in err_str.lower() or "allowance" in err_str.lower():
        print(f"❌ Insufficient funds/allowance: {err_str[:300]}")
    else:
        print(f"❌ Error: {err_str[:300]}")

print(f"\n--- Test Complete ---")
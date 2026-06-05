"""
Phase 2.5 Micro Live Test - Place a $0.50 order via CLOB V2 API using JP-01 proxy.
Tests different signature types with the new clean EOA wallet.
"""
import os, sys, time, json
sys.path.insert(0, ".")

# Load proxy
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

# Load new wallet credentials from .env
env_path = Path("/home/roy/polymarket-arb/.env")
for line in env_path.read_text().splitlines():
    line = line.strip()
    if line.startswith("#") or not line or "=" not in line:
        continue
    key, _, val = line.partition("=")
    os.environ.setdefault(key.strip(), val.strip())

# Also load wallet_new.env for deposit wallet
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

# Print wallet info
pk = os.environ.get("PRIVATE_KEY", "")
addr = Account.from_key(pk).address
print(f"=" * 60)
print(f"  Phase 2.5 Micro Live Test")
print(f"=" * 60)
print(f"Wallet: {addr}")
print(f"Deposit Wallet: {DEPOSIT_WALLET}")

# Check balances
w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
matic_bal = w3.from_wei(w3.eth.get_balance(Web3.to_checksum_address(addr)), "ether")
usdc_addr = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
erc20_abi = [{"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}]
usdc = w3.eth.contract(address=usdc_addr, abi=erc20_abi)
usdc_bal = usdc.functions.balanceOf(Web3.to_checksum_address(addr)).call() / 1e6
deposit_code = w3.eth.get_code(Web3.to_checksum_address(DEPOSIT_WALLET))
print(f"POL: {matic_bal:.4f}")
print(f"USDC: {usdc_bal:.2f}")
print(f"Deposit Wallet: {DEPOSIT_WALLET} ({'DEPLOYED' if len(deposit_code) > 0 else 'NOT DEPLOYED'})")

# Create V2 client
from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import OrderArgs, OrderType

host = "https://clob.polymarket.com"
chain_id = 137

# Inject proxy into httpx
import httpx
import py_clob_client_v2.http_helpers.helpers as _v2h
proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
if proxy:
    _v2h._http_client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True)
    print(f"Proxy: {proxy}")

# Load API credentials
api_key = os.environ.get("API_KEY", "")
api_secret = os.environ.get("API_SECRET", "")
api_passphrase = os.environ.get("API_PASSPHRASE", "")

print(f"\n--- Creating V2 CLOB Client ---")
if api_key and api_secret and api_passphrase:
    print(f"Using existing API key: {api_key}")
    client = ClobClient(host, key=pk, chain_id=chain_id)
    # Set API credentials after creation
    client.api_key = api_key
    client.api_secret = api_secret
    client.api_passphrase = api_passphrase
else:
    print("Creating new API key...")
    client = ClobClient(host, key=pk, chain_id=chain_id)
    try:
        from py_clob_client_v2.clob_types import ApiCreds
        creds = client.create_api_key()
        print(f"API Key created: {creds.api_key}")
        api_key = creds.api_key
        api_secret = creds.api_secret  
        api_passphrase = creds.api_passphrase
    except Exception as e:
        print(f"Error creating API key: {type(e).__name__}: {str(e)[:300]}")
        sys.exit(1)

# Get a market to trade
print(f"\n--- Finding Market to Trade ---")
try:
    markets = client.get_markets()
    if isinstance(markets, dict):
        markets = markets.get("data", markets.get("markets", []))
    
    # Find a market with good liquidity
    target_market = None
    for m in markets:
        vol = float(m.get("volumeNum", 0) or 0)
        liq = float(m.get("liquidityNum", 0) or 0)
        if vol > 1000 and liq > 500:
            target_market = m
            break
    
    if not target_market:
        # Just pick the first active market
        for m in markets:
            if m.get("active", False):
                target_market = m
                break
    
    if target_market:
        q = target_market.get("question", "?")[:60]
        condition_id = target_market.get("conditionId", "")
        tokens = target_market.get("tokens", [])
        print(f"Market: {q}")
        print(f"Condition ID: {condition_id[:20]}...")
        print(f"Tokens: {len(tokens)}")
        
        # Find YES and NO token IDs
        yes_token = None
        no_token = None
        for t in tokens:
            outcome = t.get("outcome", "").lower()
            if outcome == "yes":
                yes_token = t.get("token_id", "")
            elif outcome == "no":
                no_token = t.get("token_id", "")
        print(f"YES token: {yes_token[:20]}..." if yes_token else "YES token: NOT FOUND")
        print(f"NO token: {no_token[:20]}..." if no_token else "NO token: NOT FOUND")
    else:
        print("No suitable market found!")
        sys.exit(1)
except Exception as e:
    print(f"Error finding market: {type(e).__name__}: {str(e)[:300]}")
    sys.exit(1)

# Get orderbook
if yes_token:
    print(f"\n--- Getting Orderbook ---")
    try:
        book = client.get_order_book(yes_token)
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        print(f"Bids: {len(bids)}, Asks: {len(asks)}")
        if bids:
            print(f"  Best bid: {bids[0].get('price', 'N/A')} size={bids[0].get('size', 'N/A')}")
        if asks:
            print(f"  Best ask: {asks[0].get('price', 'N/A')} size={asks[0].get('size', 'N/A')}")
    except Exception as e:
        print(f"Error getting orderbook: {type(e).__name__}: {str(e)[:200]}")

# Try placing a small order with different signature types
print(f"\n--- Attempting Order Placement ---")
print(f"Market: {target_market.get('question', '?')[:50]}")
print(f"Token: YES")
print(f"Amount: $0.50")
print(f"Side: BUY")

# Try signature_type=0 (EOA) first - might work with clean EOA
for sig_type_name, sig_type_val in [("EOA (0)", 0), ("POLY_PROXY (1)", 1), ("POLY_1271 (3)", 3)]:
    print(f"\n  Trying signature_type={sig_type_name}...")
    try:
        # Build a small BUY order for YES token at best ask price
        price = 0.50  # Limit order at 50 cents
        size = 1  # 1 share = ~$0.50
        
        # Determine funder based on signature type
        if sig_type_val == 3:
            funder = DEPOSIT_WALLET
        else:
            funder = addr
        
        order_args = OrderArgs(
            price=price,
            size=size,
            side="BUY",
            token_id=yes_token,
        )
        
        # Create signed order
        signed_order = client.create_order(order_args)
        
        print(f"  Signed order created")
        print(f"  Order hash: {signed_order.get('hash', signed_order.get('orderHash', 'N/A'))}")
        
        # Submit the order
        result = client.post_order(signed_order, OrderType.GTC)
        print(f"  ✅ ORDER SUBMITTED: {result}")
        
        # If we got here, the order was placed successfully!
        order_id = result.get("orderID", result.get("order_id", result.get("id", "")))
        if order_id:
            print(f"  Order ID: {order_id}")
            
            # Wait a bit and check order status
            time.sleep(2)
            try:
                status = client.get_order(order_id)
                print(f"  Order status: {status}")
            except Exception as e:
                print(f"  Could not check status: {str(e)[:100]}")
        
        # If successful, break out of the loop
        print("\n✅ Order placement SUCCESSFUL!")
        break
        
    except Exception as e:
        err_str = str(e)
        if "geoblock" in err_str.lower():
            print(f"  ❌ GEOBLOCKED: {err_str[:200]}")
            break  # No point trying other sig types if geoblocked
        elif "not allowed" in err_str.lower() or "maker address" in err_str.lower():
            print(f"  ❌ {err_str[:200]}")
        elif "deposit" in err_str.lower():
            print(f"  ❌ Deposit wallet issue: {err_str[:200]}")
        else:
            print(f"  ❌ {type(e).__name__}: {err_str[:200]}")

print(f"\n--- Test Complete ---")
print(f"\nWallet: {addr}")
print(f"Deposit Wallet: {DEPOSIT_WALLET} ({'DEPLOYED' if len(w3.eth.get_code(Web3.to_checksum_address(DEPOSIT_WALLET))) > 0 else 'NOT DEPLOYED'})")
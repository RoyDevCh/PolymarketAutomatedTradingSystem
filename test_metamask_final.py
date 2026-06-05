"""Final Phase 2.5 test: sig_type=3 (POLY_1271) - should work once USDC deposited."""
import os, sys, json
from pathlib import Path
sys.path.insert(0, ".")

proxy_rc = Path.home() / ".proxyrc"
if proxy_rc.exists():
    for line in proxy_rc.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "): line = line[len("export "):]
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            if k.strip().lower().endswith("_proxy") and v.strip():
                os.environ.setdefault(k.strip(), v.strip())

for line in Path("/home/roy/polymarket-arb/.env").read_text().splitlines():
    line = line.strip()
    if line.startswith("#") or not line or "=" not in line: continue
    k, _, v = line.partition("=")
    os.environ.setdefault(k.strip(), v.strip())

from eth_account import Account
from web3 import Web3
import httpx
import py_clob_client_v2.http_helpers.helpers as _v2h

proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
if proxy:
    _v2h._http_client = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True)

from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import ApiCreds, OrderArgs, OrderType

pk = os.environ["PRIVATE_KEY"]
eoa = Account.from_key(pk).address
DEPOSIT = os.environ["DEPOSIT_WALLET"]
SIG_TYPE = int(os.environ.get("SIGNATURE_TYPE", "3"))

print("=" * 60)
print("Phase 2.5 Final Test (sig_type=3 POLY_1271)")
print("=" * 60)
print(f"EOA:     {eoa}")
print(f"Deposit: {DEPOSIT}")
print(f"SigType: {SIG_TYPE}")

# On-chain balances
w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
USDC_ADDR = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
abi = [{"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}]
usdc = w3.eth.contract(address=USDC_ADDR, abi=abi)

for name, addr in [("EOA", eoa), ("Deposit", DEPOSIT)]:
    ca = Web3.to_checksum_address(addr)
    bal = usdc.functions.balanceOf(ca).call() / 1e6
    code = len(w3.eth.get_code(ca))
    print(f"  {name} on-chain USDC: {bal:.2f} (code={code})")

creds = ApiCreds(
    api_key=os.environ["API_KEY"],
    api_secret=os.environ["API_SECRET"],
    api_passphrase=os.environ["API_PASSPHRASE"],
)

client = ClobClient(
    host="https://clob.polymarket.com",
    key=pk, chain_id=137, creds=creds,
    signature_type=SIG_TYPE, funder=DEPOSIT,
)
if proxy:
    _v2h._http_client = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True)

# Get market
hc = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True) if proxy else httpx.Client(timeout=30.0)
markets = hc.get("https://gamma-api.polymarket.com/markets",
    params={"limit": 5, "active": "true", "closed": "false", "order": "volume", "ascending": "false"}).json()
m = markets[0]
ids = json.loads(m["clobTokenIds"]) if isinstance(m["clobTokenIds"], str) else m["clobTokenIds"]
token = ids[0]
print(f"\nMarket: {m.get('question', '?')[:60]}")

# Place minimal test order (min size=5, far OTM price to avoid fill)
price, size = 0.01, 5.0
print(f"\nPlacing BUY order: price=${price}, size={size} (~${price * size:.2f})")
try:
    signed = client.create_order(OrderArgs(price=price, size=size, side="BUY", token_id=token))
    print(f"Signed: maker={signed.maker} signer={signed.signer} sigType={signed.signatureType}")
    result = client.post_order(signed, OrderType.GTC)
    print(f"\n*** ORDER PLACED ***")
    print(f"Result: {result}")
    if isinstance(result, dict):
        order_id = result.get("orderID") or result.get("order_id") or result.get("id")
        if order_id:
            print(f"Order ID: {order_id}")
            try:
                cancel = client.cancel(order_id)
                print(f"Cancelled: {cancel}")
            except Exception as ce:
                print(f"Cancel note: {ce}")
except Exception as e:
    err = str(e)
    print(f"Order error: {type(e).__name__}")
    if "balance" in err.lower() or "allowance" in err.lower():
        print("  => Address auth OK! Need to deposit USDC to Polymarket first.")
        print("  => Go to Polymarket website > Deposit > Transfer Crypto > USDC/Polygon")
        print(f"  => Deposit from MetaMask ({eoa})")
    elif "not allowed" in err.lower():
        print("  => Address still not allowed - check deposit wallet")
    else:
        print(f"  => {err[:250]}")

print("\nDone.")

"""Deploy deposit wallet via Polymarket Relayer API (no Builder credentials needed).

According to Polymarket V2 docs, WALLET-CREATE does NOT need a user signature.
It only needs the owner address and factory address.
"""
import os, sys, json, time
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
from web3 import Web3
from core.config import CONFIG

NEW_ADDRESS = "WALLET_ADDRESS_PLACEHOLDER"
OLD_ADDRESS = "OLD_EOA_PLACEHOLDER"
DEPOSIT_WALLET = "DEPOSIT_WALLET_PLACEHOLDER"
FACTORY = "0x00000000000Fb5C9ADea0298D729A0CB3823Cc07"
RELAYER_URL = "https://poly-relayer-api.polymarket.com"

proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")

print("=" * 60)
print("  Deploy Deposit Wallet via Relayer API")
print("=" * 60)

# Step 1: Check current state
w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
code = w3.eth.get_code(Web3.to_checksum_address(DEPOSIT_WALLET))
print(f"\nDeposit wallet: {DEPOSIT_WALLET}")
print(f"Code: {len(code)} bytes ({'DEPLOYED' if len(code) > 0 else 'NOT DEPLOYED'})")

if len(code) > 0:
    print("\n[OK] Deposit wallet already deployed!")
    sys.exit(0)

# Step 2: Deploy via Relayer API
# The WALLET-CREATE request doesn't need a signature
print("\nAttempting to deploy via Relayer API...")
print(f"  Owner: {NEW_ADDRESS}")
print(f"  Factory: {FACTORY}")

client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True)

payload = {
    "type": "WALLET-CREATE",
    "from": NEW_ADDRESS,
    "to": FACTORY,
}

headers = {"Content-Type": "application/json"}

# Try different approaches
approaches = [
    ("POST /submit (no auth)", "POST", f"{RELAYER_URL}/submit"),
    ("POST /wallet-create", "POST", f"{RELAYER_URL}/wallet-create"),
    ("POST /relay", "POST", f"{RELAYER_URL}/relay"),
    ("GET /deposit-address", "GET", f"{RELAYER_URL}/deposit-address?address={NEW_ADDRESS}"),
]

for name, method, url in approaches:
    print(f"\n  Trying {name}...")
    try:
        if method == "POST":
            resp = client.post(url, json=payload, headers=headers)
        else:
            resp = client.get(url, headers=headers)
        print(f"  Status: {resp.status_code}")
        body = resp.text[:300]
        print(f"  Response: {body}")
        
        if resp.status_code in [200, 201, 202]:
            print(f"\n  [OK] Deployment request accepted!")
            # Wait for confirmation
            for i in range(30):
                time.sleep(2)
                code_check = w3.eth.get_code(Web3.to_checksum_address(DEPOSIT_WALLET))
                if len(code_check) > 0:
                    print(f"\n  [OK] Deposit wallet DEPLOYED! ({len(code_check)} bytes)")
                    break
                print(f"  Waiting... ({i+1}/30)")
            break
    except httpx.ConnectError as e:
        print(f"  Connection error: {e}")
        # Try using SOCKS proxy instead
        socks_proxy = proxy.replace("http://", "socks5://") if proxy else None
        if socks_proxy:
            print(f"  Retrying with SOCKS proxy: {socks_proxy[:30]}...")
            try:
                socks_client = httpx.Client(proxy=socks_proxy, timeout=httpx.Timeout(30.0))
                if method == "POST":
                    resp = socks_client.post(url, json=payload, headers=headers)
                else:
                    resp = socks_client.get(url, headers=headers)
                print(f"  SOCKS Status: {resp.status_code}")
                print(f"  SOCKS Response: {resp.text[:300]}")
                socks_client.close()
            except Exception as socks_e:
                print(f"  SOCKS error: {socks_e}")
    except Exception as e:
        print(f"  Error: {type(e).__name__}: {e}")

# Step 3: Try with py-builder-relayer-client (might need Builder creds)
print("\n\nTrying py-builder-relayer-client (may need Builder credentials)...")
try:
    from py_builder_relayer_client.client import RelayClient
    
    relayer = RelayClient(
        relayer_url=RELAYER_URL,
        chain_id=137,
        private_key=CONFIG.wallet.private_key,
    )
    
    wallet = relayer.get_expected_deposit_wallet()
    print(f"  Expected deposit wallet: {wallet}")
    
    # Try deploying without builder creds first
    print("  Attempting deployment without builder creds...")
    try:
        result = relayer.deploy_deposit_wallet()
        print(f"  Deployment result: {result}")
        print(f"  Type: {type(result)}")
    except Exception as deploy_e:
        print(f"  Deployment error: {deploy_e}")
        
        # If builder credentials are needed, explain how to get them
        print("""
  Builder credentials are needed for deployment.
  
  To get Builder credentials:
  1. Go to https://polymarket.com/developers
  2. Register for a Builder account (free)
  3. Get Builder API Key, Secret, and Passphrase
  4. Add them to .env as BUILDER_API_KEY, BUILDER_SECRET, BUILDER_PASSPHRASE
  
  OR - Use your browser through a US VPN:
  1. Open Chrome/Firefox
  2. Configure Clash Verge to route polymarket.com through US node
  3. Go to https://polymarket.com
  4. Create a new account with the new wallet
  5. Make a small deposit/trade ($0.50)
  6. This will auto-deploy the deposit wallet
""")
except Exception as e:
    print(f"  RelayClient error: {type(e).__name__}: {e}")

# Verify final deployment status
code_final = w3.eth.get_code(Web3.to_checksum_address(DEPOSIT_WALLET))
if len(code_final) > 0:
    print(f"\n[SUCCESS] Deposit wallet is DEPLOYED ({len(code_final)} bytes)")
else:
    print(f"\n[INFO] Deposit wallet NOT deployed yet")
    print("Please deploy it using one of the methods described above.")

# Check USDC balance on new wallet
USDC_NATIVE = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
ERC20_ABI = [{"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}]
usdc = w3.eth.contract(address=USDC_NATIVE, abi=ERC20_ABI)
new_usdc = usdc.functions.balanceOf(Web3.to_checksum_address(NEW_ADDRESS)).call() / 1e6
new_matic = w3.from_wei(w3.eth.get_balance(Web3.to_checksum_address(NEW_ADDRESS)), "ether")
print(f"\nNew wallet status:")
print(f"  POL:  {new_matic:.6f}")
print(f"  USDC: {new_usdc:.2f}")
"""Deploy the Polymarket V2 deposit wallet programmatically.

This deploys the deposit wallet proxy contract on Polygon, which is required
before we can place V2 orders with signature_type=POLY_1271.

Steps:
1. Deploy the deposit wallet via the Polymarket relayer
2. Transfer USDC to the deposit wallet
3. Approve exchange contracts from the deposit wallet
4. Sync CLOB balances
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
from web3 import Web3

# Our addresses
EOA = "OLD_EOA_PLACEHOLDER"
PRIVATE_KEY = CONFIG.wallet.private_key

print("=" * 60)
print("  Polymarket V2 Deposit Wallet Deployment")
print("=" * 60)

# Step 1: Get the expected deposit wallet address
print("\n[1/4] Getting expected deposit wallet address...")

from py_builder_relayer_client.client import RelayClient
from py_builder_signing_sdk.config import BuilderConfig, BuilderApiKeyCreds

# We need builder API credentials - try without first for deployment
# The deploy_deposit_wallet does NOT require builder auth
RELAYER_URL = "https://poly-relayer-api.polymarket.com"

try:
    relayer = RelayClient(
        relayer_url=RELAYER_URL,
        chain_id=137,
        private_key=PRIVATE_KEY,
    )
    
    deposit_wallet = relayer.get_expected_deposit_wallet()
    print(f"  [OK] Expected deposit wallet: {deposit_wallet}")
    
    # Verify it matches what we found via V2 Exchange contract
    expected = "OLD_FUNDER_PLACEHOLDER"
    if deposit_wallet.lower() == expected.lower():
        print(f"  [OK] Matches V2 Exchange getSafeWalletAddress result")
    else:
        print(f"  [WARN] Different from expected: {expected}")
    
except Exception as e:
    print(f"  [FAIL] get_expected_deposit_wallet: {type(e).__name__}: {e}")
    print(f"  Trying alternative method...")
    
    # Try with proxy
    try:
        import requests
        session = requests.Session()
        session.proxies = {"https": proxy_url, "http": proxy_url}
        
        # Call relayer API directly
        from eth_account import Account
        account = Account.from_key(PRIVATE_KEY)
        
        # Get deposit wallet address from the factory
        # Factory address from V2 docs: 0x00000000000Fb5C9ADea0298D729A0CB3823Cc07
        FACTORY = "0x00000000000Fb5C9ADea0298D729A0CB3823Cc07"
        print(f"  Factory address: {FACTORY}")
        print(f"  Owner address: {EOA}")
        
    except Exception as e2:
        print(f"  Alternative also failed: {e2}")

# Step 2: Deploy the deposit wallet
print("\n[2/4] Deploying deposit wallet...")

try:
    response = relayer.deploy_deposit_wallet()
    print(f"  [OK] Deployment response: {response}")
    print(f"  Response type: {type(response)}")
    print(f"  Response dict: {vars(response) if hasattr(response, '__dict__') else str(response)[:500]}")
    
    # Poll until confirmed
    print("\n  Polling for confirmation...")
    try:
        result = relayer.poll_until_state(response, target_states=["STATE_MINED", "STATE_CONFIRMED"])
        print(f"  [OK] Deposit wallet deployed: {result}")
    except Exception as poll_e:
        print(f"  [WARN] Poll timeout: {poll_e}")
        print(f"  Let's check the transaction status manually...")
        try:
            tx_status = relayer.get_transaction(response)
            print(f"  Transaction status: {tx_status}")
        except Exception as tx_e:
            print(f"  Transaction query error: {tx_e}")

except Exception as e:
    print(f"  [FAIL] Deployment failed: {type(e).__name__}: {e}")
    
    # Try without builder config - deployment should not need it
    import traceback
    traceback.print_exc()
    
    # Try direct API call
    print("\n  Trying direct relayer API call...")
    try:
        import json
        from eth_account import Account
        account = Account.from_key(PRIVATE_KEY)
        
        payload = {
            "type": "WALLET-CREATE",
            "from": EOA,
            "to": "0x00000000000Fb5C9ADea0298D729A0CB3823Cc07",  # Deposit wallet factory
        }
        
        headers = {"Content-Type": "application/json"}
        
        session = requests.Session()
        session.proxies = {"https": proxy_url, "http": proxy_url}
        
        resp = session.post(
            f"{RELAYER_URL}/submit",
            json=payload,
            headers=headers,
            timeout=30,
        )
        print(f"  Relayer response: {resp.status_code}")
        print(f"  Body: {resp.text[:500]}")
    except Exception as api_e:
        print(f"  Direct API call failed: {api_e}")

# Step 3: Verify deployment
print("\n[3/4] Verifying deposit wallet deployment...")
w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
FUNDER = "OLD_FUNDER_PLACEHOLDER"

try:
    code = w3.eth.get_code(Web3.to_checksum_address(FUNDER))
    print(f"  Code at Funder: {len(code)} bytes")
    if len(code) > 0:
        print(f"  [OK] Deposit wallet is DEPLOYED!")
    else:
        print(f"  [WARN] Deposit wallet NOT deployed yet")
except Exception as e:
    print(f"  Code check error: {e}")

# Step 4: Check USDC balance
print("\n[4/4] Checking balances...")
USDC_NATIVE = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
ERC20_ABI = [{"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}]
usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC_NATIVE), abi=ERC20_ABI)

try:
    bal_eoa = usdc.functions.balanceOf(Web3.to_checksum_address(EOA)).call()
    print(f"  USDC on EOA ({EOA[:10]}...): {bal_eoa / 1e6:.2f}")
except Exception as e:
    print(f"  EOA balance error: {e}")

try:
    bal_funder = usdc.functions.balanceOf(Web3.to_checksum_address(FUNDER)).call()
    print(f"  USDC on Funder ({FUNDER[:10]}...): {bal_funder / 1e6:.2f}")
except Exception as e:
    print(f"  Funder balance error: {e}")

print("\n" + "=" * 60)
print("  Next steps if deployment succeeded:")
print("  1. Transfer USDC from EOA to Funder (deposit wallet)")
print("  2. Approve exchange contracts from Funder")
print("  3. Place V2 orders with signature_type=POLY_1271")
print("=" * 60)
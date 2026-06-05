"""
Deploy Polymarket V2 Deposit Wallet via direct on-chain transaction.

The deposit wallet factory address is: 0x00000000000Fb5C9ADea0298D729A0CB3823Cc07
The deployment happens by calling createProxy() on the factory contract.

Since our NEW wallet is a clean EOA (not a contract), we can send transactions
directly from it.
"""
import sys, os
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

from web3 import Web3

# Load wallet credentials from wallet_new.env
wallet_env = Path("/home/roy/polymarket-arb/wallet_new.env")
env_data = {}
if wallet_env.exists():
    for line in wallet_env.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or not line:
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            env_data[key.strip()] = val.strip()

NEW_PRIVATE_KEY = env_data.get("PRIVATE_KEY", "")
NEW_ADDRESS = env_data.get("WALLET_ADDRESS", "")
DEPOSIT_WALLET = env_data.get("DEPOSIT_WALLET", "")

print("=" * 60)
print("  Deploy Deposit Wallet (On-Chain Transaction)")
print("=" * 60)
print(f"\nNew wallet: {NEW_ADDRESS}")
print(f"Deposit wallet: {DEPOSIT_WALLET}")

if not NEW_PRIVATE_KEY:
    print("ERROR: No private key found in wallet_new.env")
    sys.exit(1)

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
if not w3.is_connected():
    w3 = Web3(Web3.HTTPProvider("https://polygon.drpc.org"))
if not w3.is_connected():
    w3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com"))

print(f"Connected to Polygon: {w3.is_connected()}")

# Check new wallet balances
new_matic = w3.from_wei(w3.eth.get_balance(Web3.to_checksum_address(NEW_ADDRESS)), "ether")
print(f"New wallet POL: {new_matic:.6f}")

# Check if deposit wallet is already deployed
if DEPOSIT_WALLET:
    code = w3.eth.get_code(Web3.to_checksum_address(DEPOSIT_WALLET))
    print(f"Deposit wallet ({DEPOSIT_WALLET[:10]}...): {len(code)} bytes ({'DEPLOYED' if len(code) > 0 else 'NOT DEPLOYED'})")
    
    if len(code) > 0:
        print("\n[OK] Deposit wallet is ALREADY DEPLOYED!")
        sys.exit(0)

# Approach 1: Direct call to the deposit wallet factory
# The factory at 0x00000000000Fb5C9ADea0298D729A0CB3823Cc07
# creates minimal proxies. We need to find the correct function signature.
FACTORY = "0x00000000000Fb5C9ADea0298D729A0CB3823Cc07"

print(f"\nApproach 1: Call factory directly...")

# Try different function selectors for the factory
import hashlib

# Common function signatures for proxy deployment
function_sigs = [
    # createProxy(address)
    "createProxy(address)",
    # deploy(address)  
    "deploy(address)",
    # create2Proxy(address,bytes32,bytes)
    "create2Proxy(address,bytes32,bytes)",
    # create(address,bytes)
    "create(address,bytes)",
    # createProxy(address,bytes)
    "createProxy(address,bytes)",
]

factory_checksum = Web3.to_checksum_address(FACTORY)
new_address_checksum = Web3.to_checksum_address(NEW_ADDRESS)

for sig in function_sigs:
    selector = Web3.keccak(text=sig)[:4].hex()
    print(f"  Trying {sig} (selector: 0x{selector})...")
    
    # Encode the function call
    # For createProxy(address), data is just the address padded to 32 bytes
    data = "0x" + selector + new_address[2:].zfill(64)
    # For functions with extra bytes param, add empty bytes
    if "bytes" in sig and "address,bytes32" in sig:
        data += "0" * 64  # bytes32 salt
        data += "0" * 64  # offset
        data += "0" * 64  # length=0
    elif "bytes" in sig:
        data += "0" * 64  # bytes offset
        data += "0" * 64  # bytes length=0
    
    # Try a static call first to see if it returns an address
    try:
        result = w3.eth.call({
            "from": new_address_checksum,
            "to": factory_checksum,
            "data": data,
        })
        if result and len(result) >= 32:
            returned_addr = "0x" + result.hex()[-40:]
            print(f"  Static call returned: {returned_addr}")
            
            if returned_addr.lower() == DEPOSIT_WALLET.lower():
                print(f"  [OK] Found correct function! Matches expected deposit wallet!")
                
                # Send the actual transaction
                nonce = w3.eth.get_transaction_count(new_address_checksum)
                gas_price = w3.eth.gas_price
                
                tx = {
                    "from": new_address_checksum,
                    "to": factory_checksum,
                    "data": data,
                    "gas": 500000,
                    "gasPrice": gas_price,
                    "nonce": nonce,
                    "chainId": 137,
                    "value": 0,
                }
                
                # Estimate gas first
                try:
                    gas_estimate = w3.eth.estimate_gas(tx)
                    tx["gas"] = gas_estimate + 10000
                    print(f"  Gas estimate: {gas_estimate}")
                    print(f"  Gas cost: {w3.from_wei(gas_estimate * gas_price, 'ether'):.4f} POL")
                except Exception as ge:
                    print(f"  Gas estimation failed: {ge}")
                    print(f"  Using default gas: 500000")
                
                # Sign and send
                signed = w3.eth.account.sign_transaction(tx, NEW_PRIVATE_KEY)
                tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                print(f"  Transaction hash: {tx_hash.hex()}")
                
                # Wait for confirmation
                print(f"  Waiting for confirmation...")
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                print(f"  Status: {'OK' if receipt.status == 1 else 'FAILED'}")
                print(f"  Gas used: {receipt.gasUsed}")
                
                # Check if deposit wallet is now deployed
                code = w3.eth.get_code(Web3.to_checksum_address(DEPOSIT_WALLET))
                if len(code) > 0:
                    print(f"\n  [SUCCESS] Deposit wallet DEPLOYED! ({len(code)} bytes)")
                else:
                    print(f"\n  [WARN] Deposit wallet still not deployed after tx")
                break
    except Exception as e:
        err_str = str(e)
        if "execution reverted" in err_str.lower() or "revert" in err_str.lower():
            print(f"  Reverted (function doesn't exist or wrong args)")
        else:
            print(f"  Error: {type(e).__name__}: {err_str[:100]}")

# Verify final state
print("\n" + "=" * 60)
print("  Final Status")
print("=" * 60)
if DEPOSIT_WALLET:
    code = w3.eth.get_code(Web3.to_checksum_address(DEPOSIT_WALLET))
    status = "DEPLOYED" if len(code) > 0 else "NOT DEPLOYED"
    print(f"  Deposit wallet: {DEPOSIT_WALLET}")
    print(f"  Status: {status}")
    
    if len(code) == 0:
        print("""
  The deposit wallet needs to be deployed before V2 trading can work.
  
  OPTIONS:
  
  1. Polymarket Website (easiest):
     - Open browser with US/JP VPN (use your local Clash Verge Rev)
     - Go to https://polymarket.com
     - Connect MetaMask with private key: {NEW_PRIVATE_KEY[:8]}...
     - Make a small deposit and trade ($0.50)
     - This will auto-deploy the deposit wallet
  
  2. Polymarket Builder API:
     - Register at https://polymarket.com/developers
     - Get Builder API Key, Secret, Passphrase
     - Add to .env and re-run deployment
  
  3. Wait and use V1-compatible approach:
     - Some V1-era wallets may still work with certain signature types
     - This is not guaranteed with the V2 backend
""".replace("{NEW_PRIVATE_KEY[:8]}", NEW_PRIVATE_KEY[:8]))

new_matic_final = w3.from_wei(w3.eth.get_balance(Web3.to_checksum_address(NEW_ADDRESS)), "ether")
USDC_NATIVE = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
ERC20_ABI = [{"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}]
usdc = w3.eth.contract(address=USDC_NATIVE, abi=ERC20_ABI)
new_usdc = usdc.functions.balanceOf(Web3.to_checksum_address(NEW_ADDRESS)).call() / 1e6

print(f"\n  New wallet balances:")
print(f"  POL:  {new_matic_final:.6f}")
print(f"  USDC: {new_usdc:.2f}")
"""Transfer POL and USDC from old wallet to new wallet, then deploy deposit wallet."""
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

from web3 import Web3
from core.config import CONFIG

# Wallets
OLD_PRIVATE_KEY = CONFIG.wallet.private_key
OLD_ADDRESS = "0x43083C461fc9b875c97032f375bf8aef81681B8e"
NEW_ADDRESS = "0xE56A44444F55aD30C87235f7C94786509881Da3A"
NEW_DEPOSIT_WALLET = "0x181242c978fb34c26068f8B154126F8Ea745C88B"

# ERC-20 ABI for USDC transfer
ERC20_ABI = [
    {"inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "recipient", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]

# Use proxy for RPC if direct fails
RPC_URLS = [
    CONFIG.wallet.rpc_url,
    "https://polygon-bor-rpc.publicnode.com",
    "https://polygon.drpc.org",
    "https://polygon-rpc.com",
]

w3 = None
for rpc in RPC_URLS:
    try:
        _w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
        if _w3.is_connected():
            w3 = _w3
            print(f"Connected to {rpc}")
            break
    except:
        continue

if not w3:
    print("FAIL: Cannot connect to any Polygon RPC")
    sys.exit(1)

USDC_NATIVE = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
usdc = w3.eth.contract(address=USDC_NATIVE, abi=ERC20_ABI)

print("\n" + "=" * 60)
print("  Fund New Wallet & Deploy Deposit Wallet")
print("=" * 60)

# Check old wallet balances
old_matic = w3.from_wei(w3.eth.get_balance(Web3.to_checksum_address(OLD_ADDRESS)), "ether")
old_usdc = usdc.functions.balanceOf(Web3.to_checksum_address(OLD_ADDRESS)).call() / 1e6
print(f"\nOld wallet ({OLD_ADDRESS[:10]}...):")
print(f"  POL:  {old_matic:.4f}")
print(f"  USDC: {old_usdc:.2f}")

# Check new wallet balances
new_matic = w3.from_wei(w3.eth.get_balance(Web3.to_checksum_address(NEW_ADDRESS)), "ether")
new_usdc = usdc.functions.balanceOf(Web3.to_checksum_address(NEW_ADDRESS)).call() / 1e6
print(f"\nNew wallet ({NEW_ADDRESS[:10]}...):")
print(f"  POL:  {new_matic:.6f}")
print(f"  USDC: {new_usdc:.2f}")

# Transfer 0.2 POL for gas
GAS_AMOUNT = w3.to_wei(0.2, "ether")  # 0.2 POL for gas

if old_matic < 0.3:
    print(f"\n[FAIL] Old wallet doesn't have enough POL for transfer ({old_matic:.4f} < 0.3)")
    sys.exit(1)

if new_matic > 0.05:
    print(f"\n[OK] New wallet already has {new_matic:.6f} POL, skip POL transfer")
else:
    print(f"\nTransferring 0.2 POL for gas...")
    nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(OLD_ADDRESS))
    tx = {
        "from": Web3.to_checksum_address(OLD_ADDRESS),
        "to": Web3.to_checksum_address(NEW_ADDRESS),
        "value": GAS_AMOUNT,
        "gas": 21000,
        "gasPrice": w3.eth.gas_price,
        "nonce": nonce,
        "chainId": 137,
    }
    
    signed = w3.eth.account.sign_transaction(tx, OLD_PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"  POL transfer tx: {tx_hash.hex()}")
    
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    print(f"  POL transfer status: {'OK' if receipt.status == 1 else 'FAILED'}")

# Transfer 50 USDC (leave some for old wallet)
USDC_AMOUNT = int(50 * 1e6)  # 50 USDC

if old_usdc < 51:
    USDC_AMOUNT = int((old_usdc - 1) * 1e6)  # Leave 1 USDC in old wallet
    print(f"\nAdjusting USDC transfer to {USDC_AMOUNT/1e6:.2f} USDC (leaving 1 in old wallet)")

if new_usdc > 1:
    print(f"\n[OK] New wallet already has {new_usdc:.2f} USDC, skip USDC transfer")
else:
    print(f"\nTransferring {USDC_AMOUNT/1e6:.0f} USDC...")
    nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(OLD_ADDRESS))
    tx = usdc.functions.transfer(
        Web3.to_checksum_address(NEW_ADDRESS),
        USDC_AMOUNT,
    ).build_transaction({
        "from": Web3.to_checksum_address(OLD_ADDRESS),
        "gas": 60000,
        "gasPrice": w3.eth.gas_price,
        "nonce": nonce,
        "chainId": 137,
    })
    
    signed = w3.eth.account.sign_transaction(tx, OLD_PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"  USDC transfer tx: {tx_hash.hex()}")
    
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    print(f"  USDC transfer status: {'OK' if receipt.status == 1 else 'FAILED'}")

# Verify balances after transfer
print(f"\nFinal balances:")
new_matic = w3.from_wei(w3.eth.get_balance(Web3.to_checksum_address(NEW_ADDRESS)), "ether")
new_usdc = usdc.functions.balanceOf(Web3.to_checksum_address(NEW_ADDRESS)).call() / 1e6
print(f"  New wallet POL:  {new_matic:.6f}")
print(f"  New wallet USDC: {new_usdc:.2f}")

# Check if deposit wallet is deployed
code = w3.eth.get_code(Web3.to_checksum_address(NEW_DEPOSIT_WALLET))
print(f"\n  Deposit wallet code: {len(code)} bytes ({'DEPLOYED' if len(code) > 0 else 'NOT DEPLOYED'})")

if len(code) == 0:
    print("\n" + "=" * 60)
    print("  Deposit wallet NOT deployed yet!")
    print("=" * 60)
    print("""
  Next step: Deploy the deposit wallet via Polymarket website
  
  Option A - Use Polymarket Website:
    1. Open browser with US/JP VPN
    2. Go to https://polymarket.com
    3. Connect MetaMask with the NEW wallet private key
    4. Deposit USDC and make a small trade
    5. This will auto-deploy the deposit wallet
  
  Option B - Try relayer deployment (requires Builder credentials):
    pip install py-builder-relayer-client
    # Register at https://polymarket.com/developers
    
  Option C - Direct on-chain deployment:
    python3 deploy_deposit_wallet_onchain.py
    (This will try to call the factory contract directly)
""")

print("\nDone! Update .env with new wallet credentials when ready.")
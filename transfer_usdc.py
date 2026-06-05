"""Transfer USDC from contract wallet using different approach.

The old wallet (0x4308...) has 23 bytes of code, meaning it's a contract.
We need to use a different approach to transfer USDC from it.
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

from web3 import Web3
from core.config import CONFIG

OLD_PRIVATE_KEY = CONFIG.wallet.private_key
OLD_ADDRESS = "0x43083C461fc9b875c97032f375bf8aef81681B8e"
NEW_ADDRESS = "0xE56A44444F55aD30C87235f7C94786509881Da3A"

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))

print("Checking wallet types...")

# Check old wallet code
old_code = w3.eth.get_code(Web3.to_checksum_address(OLD_ADDRESS))
print(f"Old wallet code: {len(old_code)} bytes")

# Check new wallet balances
new_matic = w3.from_wei(w3.eth.get_balance(Web3.to_checksum_address(NEW_ADDRESS)), "ether")
print(f"New wallet POL: {new_matic:.6f}")

# Check USDC balance on old wallet
USDC_NATIVE = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
ERC20_ABI = [{"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}]
usdc = w3.eth.contract(address=USDC_NATIVE, abi=ERC20_ABI)
old_usdc = usdc.functions.balanceOf(Web3.to_checksum_address(OLD_ADDRESS)).call() / 1e6
print(f"Old wallet USDC: {old_usdc:.2f}")

# Check what type of contract the old wallet is
# It might be a Gnosis Safe or a Polymarket proxy
print(f"\nAnalyzing old wallet contract...")

# Try to identify if it's a Gnosis Safe by checking the code pattern
code_hex = old_code.hex()
print(f"Contract code (hex): {code_hex[:100]}...")

# The 23-byte code ending with the EOA address is a minimal proxy (EIP-1167 or Solady)
# The last 20 bytes should be the owner address embedded in the code
if len(old_code) == 23:
    # SoladyLibClone pattern: the last 20 bytes are the implementation/owner address
    embedded_addr = "0x" + code_hex[-40:]
    print(f"Embedded address in proxy code: {embedded_addr}")
    print(f"Our EOA address:                 {OLD_ADDRESS}")
    print(f"Matches: {embedded_addr.lower() == OLD_ADDRESS.lower()}")

# Now try to transfer USDC
# Since the wallet is a contract, we might need to call it differently
# Polymarket proxy wallets usually have an execute() or similar function
# But since we have the private key, the contract should be able to sign transactions

print("\nTrying USDC transfer with higher gas limit...")

# Full ERC20 ABI for transfer
ERC20_FULL_ABI = [
    {"inputs": [{"name": "recipient", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]

usdc_full = w3.eth.contract(address=USDC_NATIVE, abi=ERC20_FULL_ABI)

# Build the transfer transaction
# Since the old wallet is a contract, the gas limit needs to be higher
USDC_AMOUNT = int(49 * 1e6)  # 49 USDC
nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(OLD_ADDRESS))
gas_price = w3.eth.gas_price

tx = usdc_full.functions.transfer(
    Web3.to_checksum_address(NEW_ADDRESS),
    USDC_AMOUNT,
).build_transaction({
    "from": Web3.to_checksum_address(OLD_ADDRESS),
    "gas": 100000,  # Higher gas for contract wallet
    "gasPrice": gas_price,
    "nonce": nonce,
    "chainId": 137,
})

print(f"  From: {OLD_ADDRESS}")
print(f"  To: {NEW_ADDRESS}")
print(f"  Amount: {USDC_AMOUNT/1e6:.0f} USDC")
print(f"  Gas: {tx['gas']}")
print(f"  Gas price: {w3.from_wei(gas_price, 'gwei'):.2f} Gwei")

# Sign and send
try:
    signed = w3.eth.account.sign_transaction(tx, OLD_PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"  USDC transfer tx: {tx_hash.hex()}")
    
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    print(f"  Status: {'OK' if receipt.status == 1 else 'FAILED'}")
    if receipt.status == 1:
        print(f"  Gas used: {receipt.gasUsed}")
    else:
        print(f"  Transaction reverted!")
        # Try to get the revert reason
        print(f"  This might mean the contract wallet doesn't support direct transfers")
        print(f"  We need to use the contract's execute() function instead")
except Exception as e:
    print(f"  Transfer error: {type(e).__name__}: {e}")
    print(f"\n  The old wallet is a contract and may not support direct USDC transfers.")
    print(f"  Alternative: Use Polymarket's withdrawal/transfer function")
    print(f"  Or: Transfer from MetaMask instead of the contract wallet")

# Check final balances
print(f"\nFinal balances:")
new_matic = w3.from_wei(w3.eth.get_balance(Web3.to_checksum_address(NEW_ADDRESS)), "ether")
new_usdc = usdc_full.functions.balanceOf(Web3.to_checksum_address(NEW_ADDRESS)).call() / 1e6
print(f"  New wallet POL:  {new_matic:.6f}")
print(f"  New wallet USDC: {new_usdc:.2f}")
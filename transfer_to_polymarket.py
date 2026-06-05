"""Check Polymarket deposit wallet and transfer USDC."""
from web3 import Web3

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))

# Polymarket deposit wallet address provided by user
polymarket_addr = "0xAe886C5740F6614e0300BC2AF95e730f150685Ff"
polymarket_checksum = Web3.to_checksum_address(polymarket_addr)

# Our wallet
our_addr = "0xE56A44444F55aD30C87235f7C94786509881Da3A"
our_checksum = Web3.to_checksum_address(our_addr)
our_pk = "0x20392882b67d9f53edebf7c53db1266d3ddef333e50261a609daa5e551e00bb8"

USDC = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
erc20_abi = [
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "recipient", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
]

usdc = w3.eth.contract(address=USDC, abi=erc20_abi)

print("=" * 60)
print("  Polymarket Deposit Wallet Check & USDC Transfer")
print("=" * 60)

# Check Polymarket address
code = w3.eth.get_code(polymarket_checksum)
pm_matic = w3.from_wei(w3.eth.get_balance(polymarket_checksum), "ether")
pm_usdc = usdc.functions.balanceOf(polymarket_checksum).call() / 1e6

print(f"\nPolymarket Address: {polymarket_addr}")
print(f"Code: {len(code)} bytes ({'DEPLOYED CONTRACT' if len(code) > 0 else 'EOA or NOT DEPLOYED'})")
print(f"MATIC: {pm_matic:.6f}")
print(f"USDC: {pm_usdc:.2f}")

# Check our wallet
our_matic = w3.from_wei(w3.eth.get_balance(our_checksum), "ether")
our_usdc = usdc.functions.balanceOf(our_checksum).call() / 1e6

print(f"\nOur Wallet: {our_addr}")
print(f"MATIC: {our_matic:.6f}")
print(f"USDC: {our_usdc:.2f}")

if our_usdc < 1:
    print("\nERROR: Not enough USDC to transfer!")
    exit(1)

# Transfer 48 USDC to Polymarket deposit address
TRANSFER_AMOUNT = int(48 * 1e6)  # 48 USDC

print(f"\n{'='*60}")
print(f"  Transferring {TRANSFER_AMOUNT/1e6:.0f} USDC to Polymarket")
print(f"{'='*60}")

nonce = w3.eth.get_transaction_count(our_checksum)
gas_price = w3.eth.gas_price

tx = usdc.functions.transfer(
    polymarket_checksum,
    TRANSFER_AMOUNT,
).build_transaction({
    "from": our_checksum,
    "gas": 60000,
    "gasPrice": gas_price,
    "nonce": nonce,
    "chainId": 137,
})

signed = w3.eth.account.sign_transaction(tx, our_pk)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
print(f"TX Hash: {tx_hash.hex()}")

receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
print(f"TX Status: {'OK' if receipt.status == 1 else 'FAILED'}")
print(f"Gas Used: {receipt.gasUsed}")

# Verify transfer
time.sleep(3)
pm_usdc_new = usdc.functions.balanceOf(polymarket_checksum).call() / 1e6
our_usdc_new = usdc.functions.balanceOf(our_checksum).call() / 1e6

print(f"\n{'='*60}")
print(f"  Transfer Complete!")
print(f"{'='*60}")
print(f"Polymarket USDC: {pm_usdc_new:.2f}")
print(f"Our Wallet USDC: {our_usdc_new:.2f}")
print(f"\nNow go to Polymarket and check your balance!")
import time
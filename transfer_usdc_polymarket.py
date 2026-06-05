"""Transfer USDC to Polymarket deposit address."""
from web3 import Web3
from eth_account import Account

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))

# Wallet credentials
pk = "0x20392882b67d9f53edebf7c53db1266d3ddef333e50261a609daa5e551e00bb8"
our_addr = Web3.to_checksum_address("0xE56A44444F55aD30C87235f7C94786509881Da3A")
polymarket_addr = Web3.to_checksum_address("0xAe886C5740F6614e0300BC2AF95e730f150685Ff")

USDC = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
erc20_abi = [
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "recipient", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
]

usdc = w3.eth.contract(address=USDC, abi=erc20_abi)

print("=" * 60)
print("  Transfer USDC to Polymarket Deposit Address")
print("=" * 60)

# Check balances
our_usdc = usdc.functions.balanceOf(our_addr).call() / 1e6
pm_usdc = usdc.functions.balanceOf(polymarket_addr).call() / 1e6
our_matic = w3.from_wei(w3.eth.get_balance(our_addr), "ether")

print(f"Our wallet: {our_addr}")
print(f"  MATIC: {our_matic:.4f}")
print(f"  USDC: {our_usdc:.2f}")
print(f"\nPolymarket address: {polymarket_addr}")
print(f"  USDC: {pm_usdc:.2f}")

# Transfer 48 USDC (leave 1 USDC for fees)
TRANSFER_AMOUNT = int(48 * 1e6)  # 48 USDC

print(f"\nTransferring {TRANSFER_AMOUNT/1e6:.0f} USDC to Polymarket...")
print(f"From: {our_addr}")
print(f"To: {polymarket_addr}")

nonce = w3.eth.get_transaction_count(our_addr)
gas_price = w3.eth.gas_price

tx = usdc.functions.transfer(
    polymarket_addr,
    TRANSFER_AMOUNT,
).build_transaction({
    "from": our_addr,
    "gas": 65000,
    "gasPrice": gas_price,
    "nonce": nonce,
    "chainId": 137,
})

signed = w3.eth.account.sign_transaction(tx, pk)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
print(f"\nTX Hash: {tx_hash.hex()}")

receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
print(f"TX Status: {'OK' if receipt.status == 1 else 'FAILED'}")
print(f"Gas Used: {receipt.gasUsed}")

if receipt.status == 1:
    print(f"\n{'='*60}")
    print(f"  TRANSFER SUCCESSFUL!")
    print(f"{'='*60}")
    
    # Verify
    pm_usdc_new = usdc.functions.balanceOf(polymarket_addr).call() / 1e6
    our_usdc_new = usdc.functions.balanceOf(our_addr).call() / 1e6
    print(f"\nPolymarket address USDC: {pm_usdc_new:.2f}")
    print(f"Our wallet USDC: {our_usdc_new:.2f}")
    
    print(f"\nNext steps:")
    print(f"1. Go back to Polymarket website")
    print(f"2. Wait 1-2 minutes for the deposit to appear")
    print(f"3. Your Polymarket balance should show ~48 USDC")
    print(f"4. The deposit wallet should be automatically deployed")
else:
    print(f"\nTRANSFER FAILED!")
    # Check if it's because the address is an EOA
    code = w3.eth.get_code(polymarket_addr)
    print(f"Target address code: {len(code)} bytes")
    print(f"This might be an EOA that doesn't accept USDC directly")
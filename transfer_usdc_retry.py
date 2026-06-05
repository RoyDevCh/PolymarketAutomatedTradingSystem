"""Retry USDC transfer with higher gas limit."""
from web3 import Web3
from eth_account import Account
import time

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))

pk = "0x20392882b67d9f53edebf7c53db1266d3ddef333e50261a609daa5e551e00bb8"
our_addr = Web3.to_checksum_address("0xE56A44444F55aD30C87235f7C94786509881Da3A")
pm_addr = Web3.to_checksum_address("0xAe886C5740F6614e0300BC2AF95e730f150685Ff")
USDC = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")

erc20_abi = [
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "recipient", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
]

usdc = w3.eth.contract(address=USDC, abi=erc20_abi)

# Check balances
our_usdc = usdc.functions.balanceOf(our_addr).call() / 1e6
pm_usdc = usdc.functions.balanceOf(pm_addr).call() / 1e6
our_matic = w3.from_wei(w3.eth.get_balance(our_addr), "ether")

print(f"Our wallet: MATIC={our_matic:.4f}, USDC={our_usdc:.2f}")
print(f"Polymarket: USDC={pm_usdc:.2f}")

# Check failed tx
tx_hash = "0x88a5d790f9f78773a1d5c618c911146dfa7c99ba27acb6c9adc8ce4068f3b330"
try:
    receipt = w3.eth.get_transaction_receipt(tx_hash)
    print(f"\nPrevious TX status: {receipt['status']} (0=FAILED, 1=OK)")
    print(f"Previous TX gas used: {receipt['gasUsed']}")
    
    # Check if USDC was actually transferred despite "failed" status
    # Sometimes Polygon reports failed but the transfer goes through
    pm_usdc_now = usdc.functions.balanceOf(pm_addr).call() / 1e6
    our_usdc_now = usdc.functions.balanceOf(our_addr).call() / 1e6
    print(f"\nCurrent balances after previous attempt:")
    print(f"  Polymarket USDC: {pm_usdc_now:.2f}")
    print(f"  Our USDC: {our_usdc_now:.2f}")
    
    if pm_usdc_now > 0:
        print("\n[OK] USDC was transferred to Polymarket despite 'failed' status!")
        print(f"Check your Polymarket balance - it should show {pm_usdc_now:.2f} USDC")
        exit(0)
except Exception as e:
    print(f"Could not check previous tx: {e}")

if our_usdc < 48:
    print(f"\nNot enough USDC to transfer (have {our_usdc:.2f}, need 48)")
    exit(1)

# Try transfer again with higher gas and EIP-1559
print(f"\nRetrying USDC transfer with higher gas...")
TRANSFER_AMOUNT = 48000000  # 48 USDC

nonce = w3.eth.get_transaction_count(our_addr)
gas_price = w3.eth.gas_price

# EIP-1559 transaction
tx = usdc.functions.transfer(pm_addr, TRANSFER_AMOUNT).build_transaction({
    "from": our_addr,
    "gas": 200000,
    "maxFeePerGas": gas_price * 3,
    "maxPriorityFeePerGas": gas_price * 2,
    "nonce": nonce,
    "chainId": 137,
})

signed = w3.eth.account.sign_transaction(tx, pk)
tx_hash2 = w3.eth.send_raw_transaction(signed.raw_transaction)
print(f"TX Hash: {tx_hash2.hex()}")

time.sleep(3)
receipt = w3.eth.wait_for_transaction_receipt(tx_hash2, timeout=120)
print(f"Status: {'OK' if receipt.status == 1 else 'FAILED'}")
print(f"Gas Used: {receipt.gasUsed}")

if receipt.status == 1:
    pm_usdc_new = usdc.functions.balanceOf(pm_addr).call() / 1e6
    our_usdc_new = usdc.functions.balanceOf(our_addr).call() / 1e6
    print(f"\nPolymarket USDC: {pm_usdc_new:.2f}")
    print(f"Our USDC: {our_usdc_new:.2f}")
    print(f"\n[SUCCESS] USDC transferred to Polymarket!")
    print(f"Go to Polymarket and check your balance!")
else:
    print(f"\n[FAILED] Transfer failed again!")
    print(f"The target address may not support direct USDC transfers.")
    print(f"You may need to use Polymarket's deposit flow instead.")
    
    # Check if USDC was actually transferred
    pm_usdc_check = usdc.functions.balanceOf(pm_addr).call() / 1e6
    our_usdc_check = usdc.functions.balanceOf(our_addr).call() / 1e6
    print(f"\nBalance check:")
    print(f"  Polymarket USDC: {pm_usdc_check:.2f}")
    print(f"  Our USDC: {our_usdc_check:.2f}")
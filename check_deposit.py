"""Check if deposit wallet got deployed after Polymarket login."""
from web3 import Web3

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))

# Check deposit wallet
deposit = "0x181242c978fb34c26068f8B154126F8Ea745C88B"
code = w3.eth.get_code(Web3.to_checksum_address(deposit))
print(f"Deposit wallet: {deposit}")
print(f"Code size: {len(code)} bytes")
print(f"Status: {'DEPLOYED!' if len(code) > 0 else 'NOT DEPLOYED'}")

# Check new wallet balances
new_addr = "0xE56A44444F55aD30C87235f7C94786509881Da3A"
matic = w3.from_wei(w3.eth.get_balance(Web3.to_checksum_address(new_addr)), "ether")
usdc = w3.eth.contract(
    address=Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"),
    abi=[{"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]
).functions.balanceOf(Web3.to_checksum_address(new_addr)).call() / 1e6
print(f"\nNew wallet POL: {matic:.6f}")
print(f"New wallet USDC: {usdc:.2f}")
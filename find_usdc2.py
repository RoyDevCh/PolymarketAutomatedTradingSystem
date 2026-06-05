from web3 import Web3

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
our_addr = "0xE56A44444F55aD30C87235f7C94786509881Da3A"
USDC = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
transfer_topic = Web3.keccak(text="Transfer(address,address,uint256)").hex()

# Get USDC transfers FROM our address
print("USDC transfers FROM our EOA:")
logs = w3.eth.get_logs({
    "fromBlock": max(0, w3.eth.block_number - 100000),
    "toBlock": "latest",
    "address": USDC,
    "topics": [transfer_topic, "0x" + our_addr[2:].zfill(64)],
})
for log in logs:
    to_addr = "0x" + log["topics"][2].hex()[-40:]
    value = int(log["data"].hex(), 16) / 1e6
    block = log["blockNumber"]
    print(f"  Block {block}: -> {to_addr[:10]}...{to_addr[-6:]}  {value:.2f} USDC")

# Get USDC transfers TO our address
print("\nUSDC transfers TO our EOA:")
logs = w3.eth.get_logs({
    "fromBlock": max(0, w3.eth.block_number - 100000),
    "toBlock": "latest",
    "address": USDC,
    "topics": [transfer_topic, None, "0x" + our_addr[2:].zfill(64)],
})
for log in logs:
    from_addr = "0x" + log["topics"][1].hex()[-40:]
    value = int(log["data"].hex(), 16) / 1e6
    block = log["blockNumber"]
    print(f"  Block {block}: from {from_addr[:10]}...{from_addr[-6:]}  {value:.2f} USDC")

# Also check the Polymarket addresses
print("\n--- All known addresses ---")
addrs = [
    "0xE56A44444F55aD30C87235f7C94786509881Da3A",  # Our EOA
    "0xAe886C5740F6614e0300BC2AF95e730f150685Ff",   # Polymarket deposit
    "0x6b1fda796ffdd756d06cf20ce43f3c8a172e60ee",    # Polymarket API addr
    "0x43083C461fc9b875c97032f375bf8aef81681B8e",     # Old wallet
    "0x181242c978fb34c26068f8B154126F8Ea745C88B",     # Our old deposit wallet
]

for addr in addrs:
    ca = Web3.to_checksum_address(addr)
    matic = w3.from_wei(w3.eth.get_balance(ca), "ether")
    usdc_bal = w3.eth.contract(address=USDC, abi=[{"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}]).functions.balanceOf(ca).call() / 1e6
    code_len = len(w3.eth.get_code(ca))
    print(f"  {addr[:10]}...{addr[-6:]}: MATIC={matic:.4f}, USDC={usdc_bal:.2f}, code={code_len}")

# Check old wallet
print("\n--- Old wallet USDC transfers ---")
old_addr = "0x43083C461fc9b875c97032f375bf8aef81681B8e"
logs = w3.eth.get_logs({
    "fromBlock": max(0, w3.eth.block_number - 100000),
    "toBlock": "latest",
    "address": USDC,
    "topics": [transfer_topic, "0x" + old_addr[2:].zfill(64)],
})
for log in logs[-5:]:
    to_addr = "0x" + log["topics"][2].hex()[-40:]
    value = int(log["data"].hex(), 16) / 1e6
    block = log["blockNumber"]
    print(f"  Block {block}: {old_addr[:10]}... -> {to_addr[:10]}...{to_addr[-6:]}  {value:.2f} USDC")
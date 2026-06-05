from web3 import Web3

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
our_addr = "0xE56A44444F55aD30C87235f7C94786509881Da3A"
USDC = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
transfer_topic = Web3.keccak(text="Transfer(address,address,uint256)").hex()

current_block = w3.eth.block_number
# Search last 5000 blocks (about 6 hours on Polygon)
from_block = current_block - 5000

print(f"Current block: {current_block}")
print(f"Searching blocks {from_block} to {current_block}")
print()

# Check all known addresses
addrs = {
    "Our_EOA": "0xE56A44444F55aD30C87235f7C94786509881Da3A",
    "PM_deposit": "0xAe886C5740F6614e0300BC2AF95e730f150685Ff",
    "PM_API": "0x6b1fda796ffdd756d06cf20ce43f3c8a172e60ee",
    "Old_wallet": "0x43083C461fc9b875c97032f375bf8aef81681B8e",
    "Old_deposit": "0x181242c978fb34c26068f8B154126F8Ea745C88B",
}

erc20_abi = [{"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}]
usdc = w3.eth.contract(address=USDC, abi=erc20_abi)

print("Address balances:")
for name, addr in addrs.items():
    ca = Web3.to_checksum_address(addr)
    matic = w3.from_wei(w3.eth.get_balance(ca), "ether")
    usdc_bal = usdc.functions.balanceOf(ca).call() / 1e6
    code_len = len(w3.eth.get_code(ca))
    print(f"  {name:<15} {addr[:10]}...{addr[-6:]}: MATIC={matic:.6f}, USDC={usdc_bal:.2f}, code={code_len}")

# Search for USDC transfers involving our EOA
print("\nUSDC transfers FROM our EOA (last 5000 blocks):")
try:
    logs = w3.eth.get_logs({
        "fromBlock": from_block,
        "toBlock": current_block,
        "address": USDC,
        "topics": [transfer_topic, "0x" + our_addr[2:].zfill(64)],
    })
    for log in logs:
        to_addr = "0x" + log["topics"][2].hex()[-40:]
        value = int(log["data"].hex(), 16) / 1e6
        block = log["blockNumber"]
        print(f"  Block {block}: -> {to_addr[:10]}...{to_addr[-6:]}  {value:.2f} USDC")
except Exception as e:
    print(f"  Error: {e}")

# Also check Polymarket deposit address
print("\nUSDC transfers involving Polymarket deposit (0xAe88...):")
pm_addr = "0xAe886C5740F6614e0300BC2AF95e730f150685Ff"
try:
    # Transfers TO deposit
    logs = w3.eth.get_logs({
        "fromBlock": from_block,
        "toBlock": current_block,
        "address": USDC,
        "topics": [transfer_topic, None, "0x" + pm_addr[2:].zfill(64)],
    })
    for log in logs:
        from_addr = "0x" + log["topics"][1].hex()[-40:]
        value = int(log["data"].hex(), 16) / 1e6
        block = log["blockNumber"]
        print(f"  Block {block}: from {from_addr[:10]}...{from_addr[-6:]}  {value:.2f} USDC (TO deposit)")
except Exception as e:
    print(f"  Error: {e}")

# Transfers FROM deposit
try:
    logs = w3.eth.get_logs({
        "fromBlock": from_block,
        "toBlock": current_block,
        "address": USDC,
        "topics": [transfer_topic, "0x" + pm_addr[2:].zfill(64)],
    })
    for log in logs:
        to_addr = "0x" + log["topics"][2].hex()[-40:]
        value = int(log["data"].hex(), 16) / 1e6
        block = log["blockNumber"]
        print(f"  Block {block}: to {to_addr[:10]}...{to_addr[-6:]}  {value:.2f} USDC (FROM deposit)")
except Exception as e:
    print(f"  Error: {e}")
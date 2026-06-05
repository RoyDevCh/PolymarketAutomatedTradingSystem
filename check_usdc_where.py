"""Check where the USDC went."""
from web3 import Web3

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
USDC = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
erc20_abi = [
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"anonymous": False, "inputs": [{"indexed": True, "name": "from", "type": "address"}, {"indexed": True, "name": "to", "type": "address"}, {"indexed": False, "name": "value", "type": "uint256"}], "name": "Transfer", "type": "event"},
]

usdc = w3.eth.contract(address=USDC, abi=erc20_abi)
our_addr = Web3.to_checksum_address("0xE56A44444F55aD30C87235f7C94786509881Da3A")

# Check recent USDC transfers from our address
# Transfer event: from=our_addr
transfer_topic = Web3.keccak_hex("Transfer(address,address,uint256)")
from_topic = "0x" + our_addr[2:].zfill(64)

# Get latest block
latest = w3.eth.block_number
print(f"Latest block: {latest}")

# Search for Transfer events from our address in the last 10000 blocks
from_block = max(0, latest - 10000)
print(f"Searching blocks {from_block} to {latest}...")

logs = usdc.events.Transfer().get_logs(
    fromBlock=from_block,
    toBlock=latest,
    argument_filters={"from": our_addr}
)

print(f"\nFound {len(logs)} USDC transfers from our address:")
for log in logs[-5:]:  # Last 5 transfers
    from_addr = log["args"]["from"]
    to_addr = log["args"]["to"]
    value = log["args"]["value"] / 1e6
    block = log["blockNumber"]
    tx_hash = log["transactionHash"].hex()
    print(f"  Block {block}: {from_addr[:10]}... -> {to_addr[:10]}...  {value:.2f} USDC  TX: {tx_hash[:20]}...")

# Also check the old wallet
old_addr = Web3.to_checksum_address("0x43083C461fc9b875c97032f375bf8aef81681B8e")
old_usdc = usdc.functions.balanceOf(old_addr).call() / 1e6
print(f"\nOld wallet USDC: {old_usdc:.2f}")

# Check all addresses we know about
all_addrs = [
    "0xE56A44444F55aD30C87235f7C94786509881Da3A",  # Our EOA
    "0xAe886C5740F6614e0300BC2AF95e730f150685Ff",   # Polymarket deposit
    "0x6b1fda796ffdd756d06cf20ce43f3c8a172e60ee",    # Polymarket API address
    "0x181242c978fb34c26068f8B154126F8Ea745C88B",     # Our old deposit wallet
    "0x43083C461fc9b875c97032f375bf8aef81681B8e",     # Old wallet
]

print("\nAll known addresses balances:")
for addr in all_addrs:
    ca = Web3.to_checksum_address(addr)
    matic = w3.from_wei(w3.eth.get_balance(ca), "ether")
    usdc_bal = usdc.functions.balanceOf(ca).call() / 1e6
    code_len = len(w3.eth.get_code(ca))
    print(f"  {addr[:10]}...{addr[-6:]}: MATIC={matic:.4f}, USDC={usdc_bal:.2f}, code={code_len}")
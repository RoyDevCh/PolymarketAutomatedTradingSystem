from web3 import Web3
w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
USDC = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
erc20_abi = [{"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}]
usdc = w3.eth.contract(address=USDC, abi=erc20_abi)

addrs = {
    "Our_EOA": "0xE56A44444F55aD30C87235f7C94786509881Da3A",
    "Polymarket_deposit": "0xAe886C5740F6614e0300BC2AF95e730f150685Ff",
    "Polymarket_API": "0x6b1fda796ffdd756d06cf20ce43f3c8a172e60ee",
    "Old_wallet": "0x43083C461fc9b875c97032f375bf8aef81681B8e",
}

for name, addr in addrs.items():
    ca = Web3.to_checksum_address(addr)
    matic = w3.from_wei(w3.eth.get_balance(ca), "ether")
    usdc_bal = usdc.functions.balanceOf(ca).call() / 1e6
    code_len = len(w3.eth.get_code(ca))
    print(f"{name}: MATIC={matic:.4f}, USDC={usdc_bal:.2f}, code={code_len}")

# Check Polymarket deposit wallet bytecode
pm = Web3.to_checksum_address("0xAe886C5740F6614e0300BC2AF95e730f150685Ff")
code = w3.eth.get_code(pm)
print(f"\nPolymarket deposit code ({len(code)} bytes): {code.hex()[:120]}...")

# Check recent USDC transfer from our EOA
print("\nChecking recent USDC transfers from our EOA...")
from web3.middleware import geth_poa
our_addr = Web3.to_checksum_address("0xE56A44444F55aD30C87235f7C94786509881Da3A")
transfer_topic = Web3.keccak(text="Transfer(address,address,uint256)").hex()

logs = w3.eth.get_logs({
    "fromBlock": max(0, w3.eth.block_number - 50000),
    "toBlock": "latest",
    "address": USDC,
    "topics": [transfer_topic, "0x" + our_addr[2:].zfill(64)],
})

print(f"Found {len(logs)} USDC transfers from our EOA")
for log in logs[-3:]:
    to_addr = "0x" + log["topics"][2].hex()[-40:]
    value = int(log["data"].hex(), 16) / 1e6
    block = log["blockNumber"]
    print(f"  Block {block}: -> {to_addr[:10]}...{to_addr[-6:]}  {value:.2f} USDC")
from web3 import Web3

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))

# Check factory contract
FACTORY = "0x00000000000Fb5C9ADea0298D729A0CB3823Cc07"
DEPOSIT = "0x181242c978fb34c26068f8B154126F8Ea745C88B"
NEW_ADDR = "0xE56A44444F55aD30C87235f7C94786509881Da3A"

for addr, name in [(FACTORY, "Factory"), (DEPOSIT, "Deposit Wallet"), (NEW_ADDR, "New Wallet")]:
    code = w3.eth.get_code(Web3.to_checksum_address(addr))
    deployed = "DEPLOYED" if len(code) > 0 else "NOT DEPLOYED"
    print(f"{name}: {len(code)} bytes - {deployed}")

# Try to call the factory with different methods
print("\nTrying factory function selectors...")

# These are the actual function selectors from the deployed contract
selectors = {
    "0x6140c54c": "createProxy(address)",  # Standard ERC-1167
    "0xd4fc2a0c": "create2Proxy(address,bytes32,bytes)",
    "0x4f1ef286": "create(address,bytes)",  # Upgradeable proxy
}

for selector, name in selectors.items():
    padded_addr = NEW_ADDR[2:].zfill(64)
    data = "0x" + selector + padded_addr
    print(f"\n  Trying {name} ({selector})...")
    try:
        result = w3.eth.call({
            "from": Web3.to_checksum_address(NEW_ADDR),
            "to": Web3.to_checksum_address(FACTORY),
            "data": data,
        })
        print(f"    Result: {result.hex()[:66]}")
        if len(result) >= 32:
            addr = "0x" + result.hex()[-40:]
            print(f"    Returned address: {addr}")
    except Exception as e:
        err_str = str(e)
        if "revert" in err_str.lower():
            print(f"    Reverted: function doesn't exist or wrong args")
        else:
            print(f"    Error: {err_str[:100]}")

# Also try without any data (just send ETH)
print("\nTrying bare transaction to factory (no data)...")
nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(NEW_ADDR))
gas_price = w3.eth.gas_price
balance = w3.eth.get_balance(Web3.to_checksum_address(NEW_ADDR))
print(f"New wallet balance: {Web3.from_wei(balance, 'ether'):.6f} POL")
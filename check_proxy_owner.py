"""Check deposit wallet proxy owner and relationship to PM API address."""
from web3 import Web3

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))

DEPOSIT = Web3.to_checksum_address("0xAe886C5740F6614e0300BC2AF95e730f150685Ff")
PM_API = Web3.to_checksum_address("0x6b1fda796ffdd756d06cf20ce43f3c8a172e60ee")
OUR_EOA = Web3.to_checksum_address("0xE56A44444F55aD30C87235f7C94786509881Da3A")

code = w3.eth.get_code(DEPOSIT)
print(f"Deposit wallet code ({len(code)} bytes): {code.hex()}")

# EIP-1167 minimal proxy: extract implementation address from bytecode
if len(code) == 23:
    # format: 363d3d373d3d3d363d73<impl20bytes>5af43d82803e903d91602b57fd5bf3
    impl = "0x" + code.hex()[20:60]
    print(f"Implementation: {impl}")

# Try common proxy owner() selectors
owner_selectors = {
    "owner()": "0x8da5cb5b",
    "getOwners()": "0xa0e67e2b",
    "getOwner()": "0x893d20e8",
}

for name, sel in owner_selectors.items():
    try:
        result = w3.eth.call({"to": DEPOSIT, "data": sel})
        if len(result) >= 32:
            addr = "0x" + result.hex()[-40:]
            print(f"{name}: {addr}")
    except Exception as e:
        print(f"{name}: call failed ({type(e).__name__})")

# Compare addresses
print(f"\nPM API addr:  {PM_API}")
print(f"Our EOA:      {OUR_EOA}")
print(f"Deposit:      {DEPOSIT}")

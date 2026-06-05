from web3 import Web3

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))

FACTORY = Web3.to_checksum_address("0x00000000000Fb5C9ADea0298D729A0CB3823Cc07")
NEW_ADDR = Web3.to_checksum_address("0xE56A44444F55aD30C87235f7C94786509881Da3A")
DEPOSIT = Web3.to_checksum_address("0x181242c978fb34c26068f8B154126F8Ea745C88B")

# Try calling the factory with proper encoding
print("Testing factory function calls...")

# createProxy(address) - selector: 0x6140c54c
selector = "6140c54c"
padded_addr = NEW_ADDR[2:].zfill(64)
data = "0x" + selector + padded_addr
print(f"\ncall data: {data}")

try:
    result = w3.eth.call({
        "from": NEW_ADDR,
        "to": FACTORY,
        "data": data,
    })
    print(f"createProxy result: {result.hex()}")
    if len(result) >= 32:
        returned_addr = "0x" + result.hex()[-40:]
        print(f"Returned address: {Web3.to_checksum_address(returned_addr)}")
except Exception as e:
    err_str = str(e)
    print(f"createProxy error: {err_str[:200]}")

# create2Proxy(address,bytes32,bytes) - selector: 0xd4fc2a0c
selector2 = "d4fc2a0c"
# address (32 bytes) + bytes32 salt + offset + length + bytes
data2 = "0x" + selector2 + padded_addr + "0" * 64 + "0" * 64 + "0" * 64 + "0" * 64
print(f"\ncreate2Proxy data: {data2[:80]}...")

try:
    result2 = w3.eth.call({
        "from": NEW_ADDR,
        "to": FACTORY,
        "data": data2,
    })
    print(f"create2Proxy result: {result2.hex()}")
except Exception as e:
    err_str = str(e)[:300]
    if "revert" in err_str.lower():
        print(f"create2Proxy: reverted (wrong args)")
    else:
        print(f"create2Proxy error: {err_str[:200]}")

# Now try to actually deploy - send a transaction to the factory
print("\nAttempting on-chain deployment...")

# Load private key from wallet_new.env
from pathlib import Path
wallet_env = Path("/home/roy/polymarket-arb/wallet_new.env")
env_data = {}
if wallet_env.exists():
    for line in wallet_env.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or not line:
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            env_data[key.strip()] = val.strip()

NEW_PRIVATE_KEY = env_data.get("PRIVATE_KEY", "")
if not NEW_PRIVATE_KEY:
    print("ERROR: No private key found")
    exit(1)

# Build a transaction to call createProxy(address)
nonce = w3.eth.get_transaction_count(NEW_ADDR)
gas_price = w3.eth.gas_price

tx = {
    "from": NEW_ADDR,
    "to": FACTORY,
    "data": data,  # createProxy(address)
    "gas": 500000,
    "gasPrice": gas_price,
    "nonce": nonce,
    "chainId": 137,
    "value": 0,
}

# Estimate gas
try:
    gas_estimate = w3.eth.estimate_gas(tx)
    print(f"Gas estimate: {gas_estimate}")
    tx["gas"] = gas_estimate + 20000
    print(f"Gas cost: {Web3.from_wei(gas_estimate * gas_price, 'ether'):.4f} POL")
except Exception as e:
    print(f"Gas estimation failed: {e}")
    print("This might mean the factory call will fail or doesn't exist")
    print("Trying anyway with default gas limit...")

# Sign and send
signed = w3.eth.account.sign_transaction(tx, NEW_PRIVATE_KEY)
print(f"\nSending transaction...")
print(f"  From: {NEW_ADDR}")
print(f"  To: {FACTORY}")
print(f"  Data: {data}")

tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
print(f"  TX Hash: {tx_hash.hex()}")

# Wait for receipt
print(f"\nWaiting for confirmation...")
receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
print(f"  Status: {'OK' if receipt.status == 1 else 'FAILED'}")
print(f"  Gas used: {receipt.gasUsed}")
print(f"  Logs: {len(receipt.logs)}")

# Check if deposit wallet is now deployed
code = w3.eth.get_code(DEPOSIT)
print(f"\nDeposit wallet code: {len(code)} bytes ({'DEPLOYED' if len(code) > 0 else 'NOT DEPLOYED'})")

if len(code) > 0:
    print("\n[SUCCESS] Deposit wallet is now DEPLOYED!")
else:
    print("\n[INFO] Deposit wallet not deployed yet. Transaction may have failed or used a different mechanism.")
    
    # Try an alternative approach: directly call the CREATE2 deployment
    # According to the V2 docs, the deposit wallet address is deterministically computed
    # using CREATE2. Let's try deploying it by sending ETH to the deployment transaction
    print("\nAlternatively, try to deploy by sending a small amount of ETH to the factory...")
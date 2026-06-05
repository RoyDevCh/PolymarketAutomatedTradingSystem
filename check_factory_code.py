from web3 import Web3

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))

# Check factory contract bytecode
FACTORY = "0x00000000000Fb5C9ADea0298D729A0CB3823Cc07"
code = w3.eth.get_code(FACTORY)

print(f"Factory bytecode ({len(code)} bytes):")
print(code.hex()[:500])

# This tiny contract (61 bytes) is likely an ERC-1167 minimal proxy pattern
# The last 20 bytes of the code are the implementation address
if len(code) <= 100:
    print(f"\nFull bytecode: {code.hex()}")
    
    # ERC-1167 minimal proxy pattern:
    # 0x363d3d373d3d3d363d3d373d3d3d363d3d373d3d3d360
    # Then the implementation address at the end
    hex_code = code.hex()
    
    # Try to decode as a known proxy pattern
    if hex_code.startswith("363d3d373d3d3d36"):
        print("Looks like ERC-1167 minimal proxy (Solady pattern)")
        # The implementation address is embedded in the code
        # For SoladyLibClone, the last 20 bytes of the 56-byte deployment code
        # are the implementation address
    
    # Actually, the factory is probably NOT a proxy itself
    # It's the CREATE2 factory that deploys deposit wallets
    # Let's look at the actual deployment documentation

# Let's try a different approach: use the py-builder-relayer-client
# which knows the correct factory ABI
print("\nTrying py-builder-relayer-client approach...")

import sys
sys.path.insert(0, "/home/roy/polymarket-arb")

try:
    from py_builder_relayer_client.client import RelayClient
    from core.config import CONFIG
    
    # Try the new wallet
    new_private_key = open("/home/roy/polymarket-arb/wallet_new.env").read()
    for line in new_private_key.splitlines():
        line = line.strip()
        if line.startswith("PRIVATE_KEY="):
            new_pk = line.split("=", 1)[1]
            break
    
    print(f"New wallet: {Web3.eth.account.from_key(new_pk).address}")
    
    relayer = RelayClient(
        relayer_url="https://poly-relayer-api.polymarket.com",
        chain_id=137,
        private_key=new_pk,
    )
    
    # Get expected deposit wallet without signing
    deposit_wallet = relayer.get_expected_deposit_wallet()
    print(f"Expected deposit wallet: {deposit_wallet}")
    
except Exception as e:
    print(f"Relayer client error: {type(e).__name__}: {e}")
    print("\nFalling back to CREATE2 calculation...")
    
    # Calculate CREATE2 address manually
    # From the V2 docs:
    # walletId = bytes32(owner) // owner address left-padded to 32 bytes
    # args = abi.encode(factory, walletId)
    # salt = keccak256(args)
    # bytecodeHash = SoladyLibClone.initCodeHashERC1967(implementation, args)
    # depositWallet = CREATE2(factory, salt, bytecodeHash)
    
    # But we need to know the implementation address, which is Polymarket-specific
    # This is embedded in the factory contract's code
    
    print("Cannot deploy without proper factory ABI or relayer access.")
    print("The deposit wallet must be deployed through the Polymarket website or relayer.")
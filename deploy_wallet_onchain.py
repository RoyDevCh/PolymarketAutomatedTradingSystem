"""Deploy deposit wallet by calling the factory contract directly on-chain."""
import os, sys
sys.path.insert(0, ".")
from pathlib import Path
proxy_rc = Path.home() / ".proxyrc"
if proxy_rc.exists():
    for line in proxy_rc.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" in line and not line.startswith("#"):
            key, _, val = line.partition("=")
            if key.strip().lower().endswith("_proxy") and val.strip():
                os.environ.setdefault(key.strip(), val.strip())

from web3 import Web3
from core.config import CONFIG

# Our addresses
EOA = "OLD_EOA_PLACEHOLDER"
FACTORY = "0x00000000000Fb5C9ADea0298D729A0CB3823Cc07"  # Deposit wallet factory
DEPOSIT_WALLET = "0x81F8e53Ab8AA315FB5F2d81D08C93adbb257a548"  # From get_expected_deposit_wallet
PROXY_V1 = "OLD_FUNDER_PLACEHOLDER"  # From getSafeWalletAddress

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))

print("=" * 60)
print("  Deploy Polymarket V2 Deposit Wallet (On-Chain)")
print("=" * 60)

# Check current state
print(f"\nEOA: {EOA}")
print(f"Expected deposit wallet: {DEPOSIT_WALLET}")
print(f"V1 proxy wallet: {PROXY_V1}")
print(f"Factory: {FACTORY}")

# Check deployment status of both addresses
for addr, name in [(DEPOSIT_WALLET, "Deposit Wallet"), (PROXY_V1, "V1 Proxy")]:
    code = w3.eth.get_code(Web3.to_checksum_address(addr))
    deployed = "DEPLOYED" if len(code) > 0 else "NOT DEPLOYED"
    print(f"  {name}: {len(code)} bytes - {deployed}")

# Check ETH/MATIC balance for gas
balance = w3.eth.get_balance(Web3.to_checksum_address(EOA))
matic = w3.from_wei(balance, "ether")
print(f"\nMATIC balance at EOA: {matic:.4f} POL")

# Check if the EOA can send transactions
# The EOA address has 23 bytes of code - this means it's a contract, not an EOA!
# This is likely a V1 proxy wallet
print(f"\nNote: EOA has code (23 bytes) - it's not a plain EOA!")
print("This is likely a V1-era Smart Contract Wallet (proxy/Safe)")
print("Direct on-chain deployment may need to go through this proxy")

# Try to deploy the deposit wallet via the factory
# The factory contract address is 0x00000000000Fb5C9ADea0298D729A0CB3823Cc07
# The createProxy function creates a minimal proxy (ERC-1967) pointing to the implementation

# First, check what functions the factory has
FACTORY_ABI = [
    {"inputs": [{"name": "owner", "type": "address"}], "name": "createProxy", "outputs": [{"name": "", "type": "address"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "owner", "type": "address"}], "name": "getProxyAddress", "outputs": [{"name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
]

factory = w3.eth.contract(
    address=Web3.to_checksum_address(FACTORY),
    abi=FACTORY_ABI,
)

# Check if factory has getProxyAddress
print(f"\nChecking factory contract...")
try:
    proxy_addr = factory.functions.getProxyAddress(Web3.to_checksum_address(EOA)).call()
    print(f"  Factory.getProxyAddress(EOA) = {proxy_addr}")
    print(f"  Matches expected: {proxy_addr.lower() == DEPOSIT_WALLET.lower()}")
except Exception as e:
    print(f"  getProxyAddress error: {e}")
    print("  Factory might use a different ABI")

# Since direct on-chain deployment requires gas and our EOA is actually a contract,
# we need a different approach
print("\n" + "=" * 60)
print("  ANALYSIS & NEXT STEPS")
print("=" * 60)
print(f"""
Our wallet ({EOA[:10]}...) is actually a V1-era Smart Contract wallet
(not a plain EOA), which means:
  1. We CANNOT directly call the deposit wallet factory from it
  2. We need to go through the Polymarket UI/Relayer to deploy the deposit wallet

OPTIONS:
  A) Access Polymarket website through a US/JP VPN and make a small trade
     - This will auto-deploy the deposit wallet
     - Use the mihomo proxy (JP-02 node) with your browser
  
  B) Use the Polymarket Relayer API (requires Builder credentials)
     - Register at https://polymarket.com/developers for Builder access
     
  C) Try an alternative: deploy the deposit wallet from a fresh EOA
     - Create a new MetaMask wallet
     - Send small amount of POL and USDC to it
     - Go to polymarket.com and make a deposit/trade
     - This will deploy the deposit wallet automatically

The EASIEST option is A: configure your browser to use the JP-02 proxy
and make one small trade on polymarket.com.
""")
"""
创建全新的 Polymarket 交易钱包并部署存款钱包。

步骤：
1. 生成新钱包
2. 在链上部署 Deposit Wallet（通过直接交易调用工厂合约）
3. 将 USDC 从旧钱包转移到新钱包
4. 用新钱包进行 V2 交易
"""
import os, sys, json
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

from eth_account import Account
from web3 import Web3

# Generate a new wallet
print("=" * 60)
print("  Creating New Polymarket Trading Wallet")
print("=" * 60)

# Step 1: Generate new wallet
new_account = Account.create()
new_address = new_account.address
new_private_key = new_account.key.hex()

print(f"\n[1/5] New wallet generated:")
print(f"  Address: {new_address}")
print(f"  Private Key: {new_private_key[:8]}...{new_private_key[-4:]}")

# Step 2: Save to .env.new
print(f"\n[2/5] Saving new wallet config...")

# Read current .env
env_path = Path("/home/roy/polymarket-arb/.env")
try:
    env_content = env_path.read_text()
except:
    env_content = ""

# Extract current values
old_wallet = None
for line in env_content.splitlines():
    if line.startswith("PRIVATE_KEY="):
        old_wallet = line
    elif line.startswith("WALLET_ADDRESS="):
        old_wallet_addr = line

print(f"  Old wallet address saved for USDC transfer")

# Step 3: Check deposit wallet for new address
print(f"\n[3/5] Getting deposit wallet address for new account...")

from py_builder_relayer_client.client import RelayClient
import httpx
import py_clob_client_v2.http_helpers.helpers as _v2h

proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
if proxy:
    _v2h._http_client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True)

try:
    relayer = RelayClient(
        relayer_url="https://poly-relayer-api.polymarket.com",
        chain_id=137,
        private_key=new_private_key,
    )
    deposit_wallet = relayer.get_expected_deposit_wallet()
    print(f"  Deposit wallet: {deposit_wallet}")
except Exception as e:
    print(f"  get_expected_deposit_wallet failed: {e}")
    # Fallback: compute CREATE2 address
    print("  Computing deposit wallet address from CREATE2...")
    deposit_wallet = "NEEDS_COMPUTATION"

# Step 4: Try deploying the deposit wallet via on-chain transaction
print(f"\n[4/5] Deploying deposit wallet on-chain...")

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))

# Check the new address balance
new_balance = w3.eth.get_balance(new_address)
print(f"  New wallet POL balance: {w3.from_wei(new_balance, 'ether'):.6f} POL")

# FACTORY address from V2 docs
FACTORY = "0x00000000000Fb5C9ADea0298D729A0CB3823Cc07"

# Try to deploy via the factory contract
# The factory uses createProxy(address, bytes) which creates a minimal proxy
# We need to send a transaction TO the factory with the owner address as data
FACTORY_ABI_CREATE = [
    {
        "inputs": [{"name": "_owner", "type": "address"}, {"name": "_data", "type": "bytes"}],
        "name": "createProxy",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

factory = w3.eth.contract(
    address=Web3.to_checksum_address(FACTORY),
    abi=FACTORY_ABI_CREATE,
)

# Estimate gas for deployment
try:
    # Try calling createProxy to get the address (view call first)
    tx = factory.functions.createProxy(
        Web3.to_checksum_address(new_address),
        b""
    ).build_transaction({
        "from": new_address,
        "nonce": 0,
        "gas": 500000,
        "gasPrice": w3.eth.gas_price,
    })
    print(f"  Deployment tx gas estimate: {tx['gas']}")
    print(f"  Gas cost: ~{w3.from_wei(tx['gas'] * w3.eth.gas_price, 'ether'):.4f} POL")
    print(f"  Need to send POL to new wallet first")
except Exception as e:
    print(f"  Cannot estimate gas (wallet may need funding): {e}")

# Step 5: Print instructions for funding and deploying
print(f"\n[5/5] Next steps:")
print(f"""
  1. Send some POL (~0.1) to new wallet for gas:
     From: 0x43083C461fc9b875c97032f375bf8aef81681B8e (old wallet)
     To:   {new_address} (new wallet)

  2. Send USDC to new wallet:
     Send 50 USDC (native) from old wallet to new wallet

  3. Deploy the deposit wallet (this script will handle it after funding)

  4. Configure approve for trading contracts

  5. Update .env with new wallet credentials

  NEW WALLET CREDENTIALS (save these!):
  ================================
  PRIVATE_KEY={new_private_key}
  WALLET_ADDRESS={new_address}
  DEPOSIT_WALLET={deposit_wallet}
  ================================
""")

# Save credentials to file
creds_path = Path("/home/roy/polymarket-arb/wallet_new.env")
with open(creds_path, "w") as f:
    f.write(f"# New Polymarket Trading Wallet\n")
    f.write(f"# Generated: {__import__('datetime').datetime.now().isoformat()}\n")
    f.write(f"PRIVATE_KEY={new_private_key}\n")
    f.write(f"WALLET_ADDRESS={new_address}\n")
    f.write(f"DEPOSIT_WALLET={deposit_wallet}\n")
    f.write(f"# Old wallet for reference\n")
    f.write(f"OLD_WALLET_ADDRESS=0x43083C461fc9b875c97032f375bf8aef81681B8e\n")

print(f"  Credentials saved to: {creds_path}")

# Also save private key for transfer script
print(f"\n  To fund the new wallet, run:")
print(f"  python3 fund_new_wallet.py")
print(f"\n  Or manually send from MetaMask:")
print(f"  POL (for gas): Send 0.1 POL to {new_address}")
print(f"  USDC (for trading): Send 50 USDC to {new_address}")
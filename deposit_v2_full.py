"""Full deposit: approve USDC via deposit wallet batch + sync CLOB balance."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")

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

for line in Path("/home/roy/polymarket-arb/.env").read_text().splitlines():
    line = line.strip()
    if line.startswith("#") or not line or "=" not in line:
        continue
    key, _, val = line.partition("=")
    os.environ.setdefault(key.strip(), val.strip())

from web3 import Web3
from eth_account import Account
import httpx
import py_clob_client_v2.http_helpers.helpers as _v2h

from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
from py_clob_client_v2.config import get_contract_config
from py_builder_relayer_client.client import RelayClient
from py_builder_relayer_client.models import DepositWalletCall
from py_builder_signing_sdk.config import BuilderConfig, BuilderApiKeyCreds

pk = os.environ["PRIVATE_KEY"]
eoa = Account.from_key(pk).address
DEPOSIT = os.environ["DEPOSIT_WALLET"]
SIG_TYPE = int(os.environ.get("SIGNATURE_TYPE", "3"))

proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
if proxy:
    _v2h._http_client = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True)

cfg = get_contract_config(137)
NATIVE_USDC = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
PUSD = Web3.to_checksum_address(cfg.collateral)
EXCHANGE = Web3.to_checksum_address(cfg.exchange)
NEG_RISK = Web3.to_checksum_address(cfg.neg_risk_exchange)
NEG_ADAPTER = Web3.to_checksum_address(cfg.neg_risk_adapter)

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
MAX_UINT = 2**256 - 1

print("=" * 60)
print("Deposit v2: Approve USDC via Deposit Wallet Batch")
print("=" * 60)
print(f"EOA: {eoa}")
print(f"Deposit: {DEPOSIT}")

# Check balances
erc20_abi = [
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf",
     "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
     "name": "allowance", "outputs": [{"name": "", "type": "uint256"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "name": "approve", "outputs": [{"name": "", "type": "bool"}],
     "stateMutability": "nonpayable", "type": "function"},
]
usdc = w3.eth.contract(address=NATIVE_USDC, abi=erc20_abi)
dep = Web3.to_checksum_address(DEPOSIT)
usdc_bal = usdc.functions.balanceOf(dep).call() / 1e6
print(f"Deposit wallet native USDC: {usdc_bal:.2f}")

def encode_approve(spender):
    return usdc.encode_abi("approve", [Web3.to_checksum_address(spender), MAX_UINT])

builder_config = BuilderConfig(
    local_builder_creds=BuilderApiKeyCreds(
        key=os.environ["BUILDER_API_KEY"],
        secret=os.environ["BUILDER_SECRET"],
        passphrase=os.environ["BUILDER_PASSPHRASE"],
    )
)

relayer = RelayClient(
    relayer_url="https://relayer-v2.polymarket.com",
    chain_id=137,
    private_key=pk,
    builder_config=builder_config,
)

# Step 1: Ensure deposit wallet registered
print("\n--- Step 1: Check/register deposit wallet ---")
try:
    deployed = relayer.get_deployed(DEPOSIT)
    print(f"Relayer deployed status: {deployed}")
    if not deployed:
        print("Deploying deposit wallet via relayer...")
        resp = relayer.deploy_deposit_wallet()
        print(f"Deploy response: {resp}")
        try:
            result = relayer.poll_until_state(resp, ["STATE_CONFIRMED", "STATE_MINED"], max_polls=40, poll_frequency=3000)
            print(f"Deploy confirmed: {result}")
        except Exception as e:
            print(f"Deploy poll: {e}")
except Exception as e:
    print(f"Deploy check error: {type(e).__name__}: {str(e)[:200]}")

# Step 2: Approve USDC to exchange contracts via deposit wallet batch
print("\n--- Step 2: Approve USDC via deposit wallet batch ---")
spenders = [
    ("Exchange", EXCHANGE),
    ("NegRisk Exchange", NEG_RISK),
    ("NegRisk Adapter", NEG_ADAPTER),
    ("pUSD", PUSD),
]

calls = [
    DepositWalletCall(target=NATIVE_USDC, value="0", data=encode_approve(spender))
    for _, spender in spenders
]

nonce = "0"
deadline = str(int(time.time()) + 3600)

try:
    resp = relayer.execute_deposit_wallet_batch(calls, DEPOSIT, nonce, deadline)
    print(f"Batch submitted: tx_id={resp.transaction_id}, hash={resp.transaction_hash}")
    result = relayer.poll_until_state(resp, ["STATE_CONFIRMED", "STATE_MINED"], max_polls=40, poll_frequency=3000)
    print(f"Batch confirmed: {result}")
except Exception as e:
    print(f"Batch error: {type(e).__name__}: {str(e)[:300]}")
    import traceback
    traceback.print_exc()

# Step 3: Verify on-chain allowances
print("\n--- Step 3: Verify allowances ---")
for name, spender in spenders:
    allow = usdc.functions.allowance(dep, Web3.to_checksum_address(spender)).call()
    print(f"  {name}: {'MAX' if allow > 10**30 else f'{allow/1e6:.2f}'}")

# Step 4: Sync CLOB balance
print("\n--- Step 4: Sync CLOB balance ---")
creds = ApiCreds(
    api_key=os.environ["API_KEY"],
    api_secret=os.environ["API_SECRET"],
    api_passphrase=os.environ["API_PASSPHRASE"],
)
client = ClobClient(
    host="https://clob.polymarket.com",
    key=pk, chain_id=137, creds=creds,
    signature_type=SIG_TYPE, funder=DEPOSIT,
)
if proxy:
    _v2h._http_client = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True)

params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=SIG_TYPE)
try:
    client.update_balance_allowance(params)
    bal = client.get_balance_allowance(params)
    print(f"CLOB balance: {bal}")
except Exception as e:
    print(f"CLOB sync error: {type(e).__name__}: {str(e)[:200]}")

print("\nDone.")

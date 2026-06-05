"""Approve PM collateral for exchange via relayer with builder creds."""
import os, sys
from pathlib import Path
sys.path.insert(0, ".")

proxy_rc = Path.home() / ".proxyrc"
if proxy_rc.exists():
    for line in proxy_rc.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "): line = line[len("export "):]
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            if k.strip().lower().endswith("_proxy") and v.strip():
                os.environ.setdefault(k.strip(), v.strip())

for line in Path("/home/roy/polymarket-arb/.env").read_text().splitlines():
    line = line.strip()
    if line.startswith("#") or not line or "=" not in line: continue
    k, _, v = line.partition("=")
    os.environ.setdefault(k.strip(), v.strip())

from web3 import Web3
from py_clob_client_v2.config import get_contract_config

pk = os.environ["PRIVATE_KEY"]
DEPOSIT = os.environ["DEPOSIT_WALLET"]
cfg = get_contract_config(137)
COLLATERAL = Web3.to_checksum_address(cfg.collateral)
EXCHANGE = Web3.to_checksum_address(cfg.exchange)

print(f"Collateral: {COLLATERAL}")
print(f"Exchange: {EXCHANGE}")
print(f"Deposit: {DEPOSIT}")

try:
    from py_builder_relayer_client.client import RelayClient
    from py_builder_relayer_client.models import SafeTransaction, OperationType
    from py_builder_signing_sdk.config import BuilderConfig, BuilderApiKeyCreds

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
    print("RelayClient with builder creds created")

    w3 = Web3()
    approve_data = w3.eth.contract(
        address=COLLATERAL,
        abi=[{"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],
              "name":"approve","outputs":[{"name":"","type":"bool"}],
              "stateMutability":"nonpayable","type":"function"}]
    ).encode_abi("approve", [EXCHANGE, 2**256 - 1])

    txn = SafeTransaction(to=COLLATERAL, operation=OperationType.Call, data=approve_data, value="0")
    resp = relayer.execute([txn], "approve collateral for exchange")
    print(f"Execute: {resp}")
    result = relayer.poll_until_state(resp, ["STATE_CONFIRMED", "STATE_MINED"], max_polls=40, poll_frequency=3000)
    print(f"Result: {result}")
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

# Check balances
w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
abi = [
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf",
     "outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],
     "name":"allowance","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
]
col = w3.eth.contract(address=COLLATERAL, abi=abi)
dep = Web3.to_checksum_address(DEPOSIT)
print(f"\nCollateral balance: {col.functions.balanceOf(dep).call()/1e6:.4f}")
print(f"Allowance to exchange: {col.functions.allowance(dep, EXCHANGE).call()/1e6:.4f}")

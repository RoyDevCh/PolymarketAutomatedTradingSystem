"""Approve USDC for exchange via py_builder_relayer_client."""
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
USDC = Web3.to_checksum_address(cfg.collateral)
EXCHANGE = Web3.to_checksum_address(cfg.exchange)

print(f"Deposit: {DEPOSIT}")
print(f"USDC: {USDC}")
print(f"Exchange: {EXCHANGE}")

# Try py_builder_relayer_client
try:
    from py_builder_relayer_client.client import RelayClient
    from py_builder_relayer_client.models import SafeTransaction, OperationType

    relayer = RelayClient(
        relayer_url="https://relayer-v2.polymarket.com",
        chain_id=137,
        private_key=pk,
    )
    print("RelayClient created")

    # Build approve transaction
    w3 = Web3()
    approve_data = w3.eth.contract(
        address=USDC,
        abi=[{"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],
              "name":"approve","outputs":[{"name":"","type":"bool"}],
              "stateMutability":"nonpayable","type":"function"}]
    ).encode_abi("approve", [EXCHANGE, 2**256 - 1])

    txn = SafeTransaction(to=USDC, operation=OperationType.Call, data=approve_data, value="0")
    print(f"Approve calldata: {approve_data[:40]}...")

    resp = relayer.execute([txn], "approve USDC for exchange")
    print(f"Execute response: {resp}")
    result = relayer.poll_until_state(resp, ["STATE_CONFIRMED", "STATE_MINED"], max_polls=30)
    print(f"Confirmed: {result}")
except Exception as e:
    print(f"Relayer error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

# Verify allowance
w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
abi = [{"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],
        "name":"allowance","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]
usdc = w3.eth.contract(address=USDC, abi=abi)
allow = usdc.functions.allowance(Web3.to_checksum_address(DEPOSIT), EXCHANGE).call()
print(f"\nAllowance after: {allow / 1e6:.2f} USDC")

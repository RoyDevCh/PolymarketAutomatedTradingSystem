"""Finish approvals and check tx status."""
import os, sys, time
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
import httpx, py_clob_client_v2.http_helpers.helpers as _v2h
from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
from py_clob_client_v2.config import get_contract_config
from py_builder_relayer_client.client import RelayClient
from py_builder_relayer_client.models import DepositWalletCall
from py_builder_signing_sdk.config import BuilderConfig, BuilderApiKeyCreds

pk = os.environ["PRIVATE_KEY"]
DEPOSIT = os.environ["DEPOSIT_WALLET"]
SIG_TYPE = int(os.environ.get("SIGNATURE_TYPE", "3"))
proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")

cfg = get_contract_config(137)
NATIVE_USDC = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
EXCHANGE = Web3.to_checksum_address(cfg.exchange)
NEG_RISK = Web3.to_checksum_address(cfg.neg_risk_exchange)
w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
MAX_UINT = 2**256 - 1
dep = Web3.to_checksum_address(DEPOSIT)

usdc = w3.eth.contract(address=NATIVE_USDC, abi=[
    {"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],
     "name":"approve","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],
     "name":"allowance","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf",
     "outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
])

# Check previous tx
tx_hash = "0xd431e6f491f15541a3efabbd52d6ce4365846e175c72dafccabaf0fc7f0289ee"
try:
    receipt = w3.eth.get_transaction_receipt(tx_hash)
    print(f"Previous tx status: {receipt.status}, block: {receipt.blockNumber}")
except Exception as e:
    print(f"Previous tx: {e}")

# Current allowances
for name, spender in [("Exchange", EXCHANGE), ("NegRisk", NEG_RISK)]:
    a = usdc.functions.allowance(dep, spender).call()
    print(f"Allowance {name}: {'MAX' if a > 10**30 else f'{a/1e6:.2f}'}")

builder_config = BuilderConfig(local_builder_creds=BuilderApiKeyCreds(
    key=os.environ["BUILDER_API_KEY"], secret=os.environ["BUILDER_SECRET"],
    passphrase=os.environ["BUILDER_PASSPHRASE"],
))
relayer = RelayClient(relayer_url="https://relayer-v2.polymarket.com", chain_id=137,
                      private_key=pk, builder_config=builder_config)

# Try nonces 3 and 4 for remaining approvals
for nonce in ["3", "4"]:
    need_calls = []
    for name, spender in [("Exchange", EXCHANGE), ("NegRisk", NEG_RISK)]:
        a = usdc.functions.allowance(dep, spender).call()
        if a < MAX_UINT // 2:
            data = usdc.encode_abi("approve", [spender, MAX_UINT])
            need_calls.append((name, DepositWalletCall(target=NATIVE_USDC, value="0", data=data)))

    if not need_calls:
        print("All approvals done!")
        break

    print(f"\nTrying nonce={nonce} for: {[n for n,_ in need_calls]}")
    deadline = str(int(time.time()) + 3600)
    try:
        resp = relayer.execute_deposit_wallet_batch(
            [c for _, c in need_calls], DEPOSIT, nonce, deadline
        )
        print(f"Submitted: hash={resp.transaction_hash}")
        time.sleep(8)
        if resp.transaction_hash:
            try:
                r = w3.eth.get_transaction_receipt(resp.transaction_hash)
                print(f"Receipt status: {r.status}")
            except:
                print("Waiting for confirmation...")
                time.sleep(10)
                r = w3.eth.get_transaction_receipt(resp.transaction_hash)
                print(f"Receipt status: {r.status}")
        break
    except Exception as e:
        err = str(e)
        print(f"Error: {err[:200]}")
        if "nonce" not in err.lower():
            break

print("\nFinal allowances:")
for name, spender in [("Exchange", EXCHANGE), ("NegRisk", NEG_RISK)]:
    a = usdc.functions.allowance(dep, spender).call()
    print(f"  {name}: {'MAX' if a > 10**30 else f'{a/1e6:.2f}'}")

# Sync and test order
if proxy: _v2h._http_client = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True)
creds = ApiCreds(api_key=os.environ["API_KEY"], api_secret=os.environ["API_SECRET"],
                 api_passphrase=os.environ["API_PASSPHRASE"])
client = ClobClient(host="https://clob.polymarket.com", key=pk, chain_id=137, creds=creds,
                    signature_type=SIG_TYPE, funder=DEPOSIT)
params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=SIG_TYPE)
client.update_balance_allowance(params)
bal = client.get_balance_allowance(params)
print(f"\nCLOB balance: {bal}")
print(f"Deposit USDC: {usdc.functions.balanceOf(dep).call()/1e6:.2f}")

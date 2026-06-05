"""Approve USDC with correct deposit wallet nonce."""
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

import httpx
from web3 import Web3
from eth_account import Account
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
if proxy: _v2h._http_client = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True)

cfg = get_contract_config(137)
NATIVE_USDC = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
EXCHANGE = Web3.to_checksum_address(cfg.exchange)
NEG_RISK = Web3.to_checksum_address(cfg.neg_risk_exchange)
NEG_ADAPTER = Web3.to_checksum_address(cfg.neg_risk_adapter)
PUSD = Web3.to_checksum_address(cfg.collateral)

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
MAX_UINT = 2**256 - 1
usdc = w3.eth.contract(address=NATIVE_USDC, abi=[
    {"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],
     "name":"approve","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],
     "name":"allowance","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf",
     "outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
])
dep = Web3.to_checksum_address(DEPOSIT)

builder_config = BuilderConfig(local_builder_creds=BuilderApiKeyCreds(
    key=os.environ["BUILDER_API_KEY"], secret=os.environ["BUILDER_SECRET"],
    passphrase=os.environ["BUILDER_PASSPHRASE"],
))
relayer = RelayClient(relayer_url="https://relayer-v2.polymarket.com", chain_id=137,
                      private_key=pk, builder_config=builder_config)

# Get nonce from relayer API
hc = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True) if proxy else httpx.Client(timeout=30.0)
headers = {
    "RELAYER_API_KEY": os.environ["BUILDER_API_KEY"],
    "RELAYER_API_KEY_ADDRESS": eoa,
}
# Try deposit wallet nonce endpoint
for url_path in [
    f"https://relayer-v2.polymarket.com/nonce?address={DEPOSIT}&type=DEPOSIT_WALLET",
    f"https://relayer-v2.polymarket.com/nonce?address={eoa}&type=DEPOSIT_WALLET",
    f"https://relayer-v2.polymarket.com/nonce?address={DEPOSIT}&type=SAFE",
]:
    try:
        r = hc.get(url_path, headers=headers)
        print(f"Nonce {url_path.split('type=')[1]}: {r.status_code} {r.text[:150]}")
    except Exception as e:
        print(f"Nonce error: {e}")

# Use nonce 2 as indicated by error
nonce = "2"
deadline = str(int(time.time()) + 3600)

def encode_approve(spender):
    return usdc.encode_abi("approve", [Web3.to_checksum_address(spender), MAX_UINT])

spenders = [("Exchange", EXCHANGE), ("NegRisk", NEG_RISK), ("Adapter", NEG_ADAPTER), ("pUSD", PUSD)]
calls = [DepositWalletCall(target=NATIVE_USDC, value="0", data=encode_approve(s)) for _, s in spenders]

print(f"\nSubmitting batch with nonce={nonce}, {len(calls)} approve calls...")
try:
    resp = relayer.execute_deposit_wallet_batch(calls, DEPOSIT, nonce, deadline)
    print(f"Submitted: id={resp.transaction_id}, hash={resp.transaction_hash}")
    result = relayer.poll_until_state(resp, ["STATE_CONFIRMED", "STATE_MINED"], "STATE_FAILED", max_polls=40, poll_frequency=3000)
    print(f"Result: {result}")
except Exception as e:
    print(f"Batch error: {type(e).__name__}: {str(e)[:300]}")

print("\nAllowances:")
for name, spender in spenders:
    a = usdc.functions.allowance(dep, Web3.to_checksum_address(spender)).call()
    print(f"  {name}: {'MAX' if a > 10**30 else f'{a/1e6:.2f}'}")

# Sync CLOB
print("\nSyncing CLOB...")
creds = ApiCreds(api_key=os.environ["API_KEY"], api_secret=os.environ["API_SECRET"],
                 api_passphrase=os.environ["API_PASSPHRASE"])
client = ClobClient(host="https://clob.polymarket.com", key=pk, chain_id=137, creds=creds,
                    signature_type=SIG_TYPE, funder=DEPOSIT)
if proxy: _v2h._http_client = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True)
params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=SIG_TYPE)
client.update_balance_allowance(params)
bal = client.get_balance_allowance(params)
print(f"CLOB balance: {bal}")

print(f"\nDeposit USDC: {usdc.functions.balanceOf(dep).call()/1e6:.2f}")

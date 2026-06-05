"""Full balance/allowance diagnosis + try all asset types."""
import os, sys, json
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

import httpx, py_clob_client_v2.http_helpers.helpers as _v2h
proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
if proxy: _v2h._http_client = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True)

from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
from py_clob_client_v2.config import get_contract_config
from web3 import Web3

pk = os.environ["PRIVATE_KEY"]
DEPOSIT = os.environ["DEPOSIT_WALLET"]
creds = ApiCreds(api_key=os.environ["API_KEY"], api_secret=os.environ["API_SECRET"],
                 api_passphrase=os.environ["API_PASSPHRASE"])

for sig in [1, 2, 3]:
    client = ClobClient(host="https://clob.polymarket.com", key=pk, chain_id=137,
                        creds=creds, signature_type=sig, funder=DEPOSIT)
    if proxy: _v2h._http_client = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True)
    print(f"\n=== sig_type={sig} ===")
    for at_name in ["COLLATERAL", "CONDITIONAL"]:
        try:
            at = getattr(AssetType, at_name)
            p = BalanceAllowanceParams(asset_type=at, signature_type=sig)
            client.update_balance_allowance(p)
            bal = client.get_balance_allowance(p)
            print(f"  {at_name}: {json.dumps(bal)}")
        except Exception as e:
            print(f"  {at_name}: {e}")

# On-chain allowances to all known spenders
cfg = get_contract_config(137)
USDC = Web3.to_checksum_address(cfg.collateral)
spenders = [cfg.exchange, cfg.neg_risk_exchange, cfg.neg_risk_adapter,
            "0xE111180000d2663C0091e4f400237545B87B996B"]
abi = [{"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],
        "name":"allowance","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
       {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf",
        "outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]
w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
usdc = w3.eth.contract(address=USDC, abi=abi)
dep = Web3.to_checksum_address(DEPOSIT)
print(f"\nOn-chain USDC balance: {usdc.functions.balanceOf(dep).call()/1e6:.2f}")
for s in spenders:
    a = usdc.functions.allowance(dep, Web3.to_checksum_address(s)).call()
    print(f"  allowance -> {s[:10]}...: {a/1e6:.2f}" if a < 10**30 else f"  allowance -> {s[:10]}...: MAX")

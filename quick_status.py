import os
from pathlib import Path
from web3 import Web3
import httpx, py_clob_client_v2.http_helpers.helpers as _v2h
from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
from py_clob_client_v2.config import get_contract_config

for line in Path("/home/roy/polymarket-arb/.env").read_text().splitlines():
    line = line.strip()
    if line.startswith("#") or not line or "=" not in line: continue
    k, _, v = line.partition("=")
    os.environ.setdefault(k.strip(), v.strip())

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
DEPOSIT = os.environ["DEPOSIT_WALLET"]
NATIVE = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
PUSD = Web3.to_checksum_address(get_contract_config(137).collateral)
abi = [{"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]
dep = Web3.to_checksum_address(DEPOSIT)
usdc = w3.eth.contract(address=NATIVE, abi=abi).functions.balanceOf(dep).call()/1e6
pusd = w3.eth.contract(address=PUSD, abi=abi).functions.balanceOf(dep).call()/1e6
print(f"Deposit wallet: USDC={usdc:.2f}, pUSD={pusd:.2f}")

proxy = os.environ.get("https_proxy")
if proxy: _v2h._http_client = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True)
client = ClobClient(host="https://clob.polymarket.com", key=os.environ["PRIVATE_KEY"], chain_id=137,
    creds=ApiCreds(api_key=os.environ["API_KEY"], api_secret=os.environ["API_SECRET"], api_passphrase=os.environ["API_PASSPHRASE"]),
    signature_type=3, funder=DEPOSIT)
params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=3)
client.update_balance_allowance(params)
bal = client.get_balance_allowance(params)
print(f"CLOB balance: {bal}")

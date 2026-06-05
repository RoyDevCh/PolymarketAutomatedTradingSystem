"""Register deposit wallet with relayer and retry balance sync."""
import os, time
from pathlib import Path
import httpx
import py_clob_client_v2.http_helpers.helpers as _v2h
from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
from py_builder_relayer_client.client import RelayClient
from py_builder_signing_sdk.config import BuilderConfig, BuilderApiKeyCreds

for line in Path("/home/roy/polymarket-arb/.env").read_text().splitlines():
    line = line.strip()
    if line.startswith("#") or not line or "=" not in line: continue
    k, _, v = line.partition("=")
    os.environ.setdefault(k.strip(), v.strip())

pk = os.environ["PRIVATE_KEY"]
DEPOSIT = os.environ["DEPOSIT_WALLET"]
proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
if proxy: _v2h._http_client = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True)

builder_config = BuilderConfig(local_builder_creds=BuilderApiKeyCreds(
    key=os.environ["BUILDER_API_KEY"], secret=os.environ["BUILDER_SECRET"],
    passphrase=os.environ["BUILDER_PASSPHRASE"],
))
relayer = RelayClient(relayer_url="https://relayer-v2.polymarket.com", chain_id=137,
                      private_key=pk, builder_config=builder_config)

print("Deployed before:", relayer.get_deployed(DEPOSIT))
try:
    resp = relayer.deploy_deposit_wallet()
    print(f"Deploy tx: {resp.transaction_hash}")
    for i in range(20):
        time.sleep(3)
        try:
            tx = relayer.get_transaction(resp.transaction_id)
            print(f"  poll {i}: {tx}")
            if tx.get("state") in ("STATE_CONFIRMED", "STATE_MINED"):
                break
        except Exception as e:
            print(f"  poll {i}: {e}")
except Exception as e:
    print(f"Deploy: {e}")

print("Deployed after:", relayer.get_deployed(DEPOSIT))

client = ClobClient(host="https://clob.polymarket.com", key=pk, chain_id=137,
    creds=ApiCreds(api_key=os.environ["API_KEY"], api_secret=os.environ["API_SECRET"],
                   api_passphrase=os.environ["API_PASSPHRASE"]),
    signature_type=3, funder=DEPOSIT)
params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=3)

for i in range(5):
    client.update_balance_allowance(params)
    bal = client.get_balance_allowance(params)
    print(f"Sync {i}: balance={bal.get('balance', '?')}")
    if bal.get("balance", "0") != "0":
        break
    time.sleep(5)

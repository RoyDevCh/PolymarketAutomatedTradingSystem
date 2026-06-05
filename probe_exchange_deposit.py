"""Probe exchange deposit functions and collateral handler."""
import os, time
from pathlib import Path
from web3 import Web3
from py_clob_client_v2.config import get_contract_config
from py_builder_relayer_client.client import RelayClient
from py_builder_relayer_client.models import DepositWalletCall
from py_builder_signing_sdk.config import BuilderConfig, BuilderApiKeyCreds
import py_clob_client_v2.http_helpers.helpers as _v2h
from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import ApiCreds, BalanceAllowanceParams, AssetType

for line in Path("/home/roy/polymarket-arb/.env").read_text().splitlines():
    line = line.strip()
    if line.startswith("#") or not line or "=" not in line: continue
    k, _, v = line.partition("=")
    os.environ.setdefault(k.strip(), v.strip())

cfg = get_contract_config(137)
w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
pk = os.environ["PRIVATE_KEY"]
DEPOSIT = os.environ["DEPOSIT_WALLET"]
EXCHANGE = Web3.to_checksum_address(cfg.exchange)
COLLATERAL_HANDLER = Web3.to_checksum_address("0xE111180000d2663C0091e4f400237545B87B996B")
NATIVE_USDC = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
dep = Web3.to_checksum_address(DEPOSIT)
AMOUNT = int(40 * 1e6)

# Try various exchange deposit ABIs
exchange_abis = [
    ("deposit(uint256)", [{"inputs":[{"name":"amount","type":"uint256"}],"name":"deposit","outputs":[],"stateMutability":"nonpayable","type":"function"}]),
    ("depositFor(address,uint256)", [{"inputs":[{"name":"account","type":"address"},{"name":"amount","type":"uint256"}],"name":"depositFor","outputs":[],"stateMutability":"nonpayable","type":"function"}]),
    ("addFunding(uint256)", [{"inputs":[{"name":"amount","type":"uint256"}],"name":"addFunding","outputs":[],"stateMutability":"nonpayable","type":"function"}]),
    ("registerToken(uint256)", []),
]

print("Probing exchange functions...")
for name, abi in exchange_abis:
    if not abi: continue
    try:
        c = w3.eth.contract(address=EXCHANGE, abi=abi)
        if "depositFor" in name:
            c.functions.depositFor(dep, AMOUNT).call({"from": dep})
        else:
            c.functions.deposit(AMOUNT).call({"from": dep})
        print(f"  {name}: SUCCESS")
    except Exception as e:
        print(f"  {name}: {type(e).__name__}: {str(e)[:80]}")

# Try collateral handler
handler_abis = [
    ("deposit(uint256)", [{"inputs":[{"name":"amount","type":"uint256"}],"name":"deposit","outputs":[],"stateMutability":"nonpayable","type":"function"}]),
    ("depositFor(address,uint256)", [{"inputs":[{"name":"account","type":"address"},{"name":"amount","type":"uint256"}],"name":"depositFor","outputs":[],"stateMutability":"nonpayable","type":"function"}]),
    ("convert(uint256)", [{"inputs":[{"name":"amount","type":"uint256"}],"name":"convert","outputs":[],"stateMutability":"nonpayable","type":"function"}]),
]
print("\nProbing collateral handler 0xE111...")
for name, abi in handler_abis:
    try:
        c = w3.eth.contract(address=COLLATERAL_HANDLER, abi=abi)
        if "depositFor" in name:
            c.functions.depositFor(dep, AMOUNT).call({"from": dep})
        else:
            getattr(c.functions, name.split("(")[0])(AMOUNT).call({"from": dep})
        print(f"  {name}: SUCCESS")
    except Exception as e:
        print(f"  {name}: {type(e).__name__}: {str(e)[:80]}")

# Try relayer batch with exchange deposit
builder_config = BuilderConfig(local_builder_creds=BuilderApiKeyCreds(
    key=os.environ["BUILDER_API_KEY"], secret=os.environ["BUILDER_SECRET"],
    passphrase=os.environ["BUILDER_PASSPHRASE"],
))
relayer = RelayClient(relayer_url="https://relayer-v2.polymarket.com", chain_id=137,
                      private_key=pk, builder_config=builder_config)

ex = w3.eth.contract(address=EXCHANGE, abi=[
    {"inputs":[{"name":"amount","type":"uint256"}],"name":"deposit","outputs":[],"stateMutability":"nonpayable","type":"function"},
])
for target_name, target, data_fn in [
    ("exchange.deposit", EXCHANGE, lambda: ex.encode_abi("deposit", [AMOUNT])),
    ("handler.deposit", COLLATERAL_HANDLER, lambda: w3.eth.contract(address=COLLATERAL_HANDLER, abi=[
        {"inputs":[{"name":"amount","type":"uint256"}],"name":"deposit","outputs":[],"stateMutability":"nonpayable","type":"function"}
    ]).encode_abi("deposit", [AMOUNT])),
]:
    for nonce in ["4", "5", "6", "7"]:
        try:
            data = data_fn()
            calls = [DepositWalletCall(target=target, value="0", data=data)]
            resp = relayer.execute_deposit_wallet_batch(calls, DEPOSIT, nonce, str(int(time.time())+3600))
            print(f"\n{target_name} nonce={nonce}: submitted {resp.transaction_hash}")
            time.sleep(10)
            r = w3.eth.get_transaction_receipt(resp.transaction_hash)
            print(f"  status={r.status}")
            if r.status == 1:
                break
        except Exception as e:
            err = str(e)[:150]
            if "nonce" not in err.lower():
                print(f"  {target_name} nonce={nonce}: {err}")
            continue
        break

# Final CLOB check
proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
if proxy: _v2h._http_client = __import__("httpx").Client(proxy=proxy, timeout=30.0, follow_redirects=True)
client = ClobClient(host="https://clob.polymarket.com", key=pk, chain_id=137,
    creds=ApiCreds(api_key=os.environ["API_KEY"], api_secret=os.environ["API_SECRET"],
                   api_passphrase=os.environ["API_PASSPHRASE"]),
    signature_type=3, funder=DEPOSIT)
params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=3)
client.update_balance_allowance(params)
print(f"\nCLOB balance: {client.get_balance_allowance(params)}")

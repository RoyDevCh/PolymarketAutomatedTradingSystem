"""Try deposit/sweep functions on deposit wallet contract."""
import os, time
from pathlib import Path
from web3 import Web3
from py_builder_relayer_client.client import RelayClient
from py_builder_relayer_client.models import DepositWalletCall
from py_builder_signing_sdk.config import BuilderConfig, BuilderApiKeyCreds
import py_clob_client_v2.http_helpers.helpers as _v2h
from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
from py_clob_client_v2.config import get_contract_config

for line in Path("/home/roy/polymarket-arb/.env").read_text().splitlines():
    line = line.strip()
    if line.startswith("#") or not line or "=" not in line: continue
    k, _, v = line.partition("=")
    os.environ.setdefault(k.strip(), v.strip())

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
pk = os.environ["PRIVATE_KEY"]
DEPOSIT = Web3.to_checksum_address(os.environ["DEPOSIT_WALLET"])
DEPOSIT_IMPL = Web3.to_checksum_address("0x58CA52ebe0DadfdF531Cde7062e76746de4Db1eB")
NATIVE = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
PUSD = Web3.to_checksum_address(get_contract_config(137).collateral)
AMOUNT = int(40 * 1e6)

erc20_abi = [{"inputs":[{"name":"account","type":"address"}],"name":"balanceOf",
              "outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]
def bals():
    u = w3.eth.contract(address=NATIVE, abi=erc20_abi).functions.balanceOf(DEPOSIT).call()/1e6
    p = w3.eth.contract(address=PUSD, abi=erc20_abi).functions.balanceOf(DEPOSIT).call()/1e6
    return u, p

print(f"Before: USDC={bals()[0]:.2f}, pUSD={bals()[1]:.2f}")

# Probe wallet-level functions
probes = [
    (DEPOSIT, "deposit(uint256)", [{"inputs":[{"name":"amount","type":"uint256"}],"name":"deposit","outputs":[],"stateMutability":"nonpayable","type":"function"}]),
    (DEPOSIT_IMPL, "deposit(uint256)", [{"inputs":[{"name":"amount","type":"uint256"}],"name":"deposit","outputs":[],"stateMutability":"nonpayable","type":"function"}]),
    (DEPOSIT, "enableTrading()", [{"inputs":[],"name":"enableTrading","outputs":[],"stateMutability":"nonpayable","type":"function"}]),
    (DEPOSIT_IMPL, "enableTrading()", [{"inputs":[],"name":"enableTrading","outputs":[],"stateMutability":"nonpayable","type":"function"}]),
    (DEPOSIT, "syncBalance()", [{"inputs":[],"name":"syncBalance","outputs":[],"stateMutability":"nonpayable","type":"function"}]),
    (DEPOSIT, "claim()", [{"inputs":[],"name":"claim","outputs":[],"stateMutability":"nonpayable","type":"function"}]),
]

for target, fname, abi in probes:
    try:
        c = w3.eth.contract(address=target, abi=abi)
        fn_name = fname.split("(")[0]
        if fn_name == "deposit":
            c.functions.deposit(AMOUNT).call({"from": DEPOSIT})
        else:
            getattr(c.functions, fn_name)().call({"from": DEPOSIT})
        print(f"  eth_call {fname} on {str(target)[:10]}...: OK")
    except Exception as e:
        print(f"  eth_call {fname} on {str(target)[:10]}...: {type(e).__name__}")

# Try batch calls for wallet deposit
builder_config = BuilderConfig(local_builder_creds=BuilderApiKeyCreds(
    key=os.environ["BUILDER_API_KEY"], secret=os.environ["BUILDER_SECRET"],
    passphrase=os.environ["BUILDER_PASSPHRASE"],
))
relayer = RelayClient(relayer_url="https://relayer-v2.polymarket.com", chain_id=137,
                      private_key=pk, builder_config=builder_config)

batch_targets = [
    ("wallet.deposit", DEPOSIT, w3.eth.contract(address=DEPOSIT, abi=[
        {"inputs":[{"name":"amount","type":"uint256"}],"name":"deposit","outputs":[],"stateMutability":"nonpayable","type":"function"}
    ]).encode_abi("deposit", [AMOUNT])),
    ("wallet.enableTrading", DEPOSIT, w3.eth.contract(address=DEPOSIT, abi=[
        {"inputs":[],"name":"enableTrading","outputs":[],"stateMutability":"nonpayable","type":"function"}
    ]).encode_abi("enableTrading", [])),
    ("impl.deposit", DEPOSIT_IMPL, w3.eth.contract(address=DEPOSIT_IMPL, abi=[
        {"inputs":[{"name":"amount","type":"uint256"}],"name":"deposit","outputs":[],"stateMutability":"nonpayable","type":"function"}
    ]).encode_abi("deposit", [AMOUNT])),
]

for label, target, data in batch_targets:
    for nonce in ["4","5","6","7","8"]:
        try:
            calls = [DepositWalletCall(target=target, value="0", data=data)]
            resp = relayer.execute_deposit_wallet_batch(calls, DEPOSIT, nonce, str(int(time.time())+3600))
            print(f"\n{label} nonce={nonce}: tx={resp.transaction_hash}")
            time.sleep(12)
            r = w3.eth.get_transaction_receipt(resp.transaction_hash)
            print(f"  status={r.status}, USDC={bals()[0]:.2f}, pUSD={bals()[1]:.2f}")
            if r.status == 1:
                break
        except Exception as e:
            err = str(e)[:120]
            if "nonce" not in err.lower():
                print(f"  {label}: {err}")
            continue
        break

proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
if proxy: _v2h._http_client = __import__("httpx").Client(proxy=proxy, timeout=30.0, follow_redirects=True)
client = ClobClient(host="https://clob.polymarket.com", key=pk, chain_id=137,
    creds=ApiCreds(api_key=os.environ["API_KEY"], api_secret=os.environ["API_SECRET"],
                   api_passphrase=os.environ["API_PASSPHRASE"]),
    signature_type=3, funder=DEPOSIT)
params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=3)
client.update_balance_allowance(params)
print(f"\nFinal: USDC={bals()[0]:.2f}, pUSD={bals()[1]:.2f}")
print(f"CLOB: {client.get_balance_allowance(params)}")

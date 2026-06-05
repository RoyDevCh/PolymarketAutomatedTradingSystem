"""Convert native USDC to pUSD via deposit wallet batch."""
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
import py_clob_client_v2.http_helpers.helpers as _v2h
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
PUSD = Web3.to_checksum_address(cfg.collateral)
PUSD_IMPL = Web3.to_checksum_address("0x6bBCef9f7ef3B6C592c99e0f206a0DE94Ad0925f")

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
dep = Web3.to_checksum_address(DEPOSIT)
AMOUNT = int(40 * 1e6)  # 40 USDC

erc20_abi = [{"inputs":[{"name":"account","type":"address"}],"name":"balanceOf",
              "outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]

def bal(token, addr):
    c = w3.eth.contract(address=token, abi=erc20_abi)
    return c.functions.balanceOf(addr).call() / 1e6

print(f"Before: USDC={bal(NATIVE_USDC, dep):.2f}, pUSD={bal(PUSD, dep):.2f}")

# Try eth_call deposit variants on pUSD
candidates = [
    ("deposit(uint256)", PUSD, [{"inputs":[{"name":"amount","type":"uint256"}],"name":"deposit","outputs":[],"stateMutability":"nonpayable","type":"function"}]),
    ("deposit(uint256)", PUSD_IMPL, [{"inputs":[{"name":"amount","type":"uint256"}],"name":"deposit","outputs":[],"stateMutability":"nonpayable","type":"function"}]),
    ("mint(uint256)", PUSD, [{"inputs":[{"name":"amount","type":"uint256"}],"name":"mint","outputs":[],"stateMutability":"nonpayable","type":"function"}]),
    ("deposit(address,uint256)", PUSD, [{"inputs":[{"name":"to","type":"address"},{"name":"amount","type":"uint256"}],"name":"deposit","outputs":[],"stateMutability":"nonpayable","type":"function"}]),
]

for name, target, abi in candidates:
    try:
        c = w3.eth.contract(address=target, abi=abi)
        fn = c.functions.deposit(AMOUNT) if "address" not in name else c.functions.deposit(dep, AMOUNT)
        # static call from deposit wallet
        fn.call({"from": dep})
        print(f"  eth_call {name} on {target[:10]}...: SUCCESS (would work)")
    except Exception as e:
        err = str(e)[:100]
        if "success" in err.lower() or err == "":
            print(f"  eth_call {name} on {target[:10]}...: might work")
        else:
            print(f"  eth_call {name} on {target[:10]}...: {type(e).__name__}: {err}")

# Try deposit via relayer batch
builder_config = BuilderConfig(local_builder_creds=BuilderApiKeyCreds(
    key=os.environ["BUILDER_API_KEY"], secret=os.environ["BUILDER_SECRET"],
    passphrase=os.environ["BUILDER_PASSPHRASE"],
))
relayer = RelayClient(relayer_url="https://relayer-v2.polymarket.com", chain_id=137,
                      private_key=pk, builder_config=builder_config)

# Build deposit call to pUSD
pusd_contract = w3.eth.contract(address=PUSD, abi=[
    {"inputs":[{"name":"amount","type":"uint256"}],"name":"deposit","outputs":[],"stateMutability":"nonpayable","type":"function"},
])
deposit_data = pusd_contract.encode_abi("deposit", [AMOUNT])

for nonce in ["4", "5", "6"]:
    print(f"\nTrying deposit via batch nonce={nonce}...")
    deadline = str(int(time.time()) + 3600)
    calls = [DepositWalletCall(target=PUSD, value="0", data=deposit_data)]
    try:
        resp = relayer.execute_deposit_wallet_batch(calls, DEPOSIT, nonce, deadline)
        print(f"Submitted: {resp.transaction_hash}")
        time.sleep(12)
        if resp.transaction_hash:
            r = w3.eth.get_transaction_receipt(resp.transaction_hash)
            print(f"Receipt: status={r.status}")
            if r.status == 1:
                print(f"After: USDC={bal(NATIVE_USDC, dep):.2f}, pUSD={bal(PUSD, dep):.2f}")
                break
    except Exception as e:
        print(f"Error: {str(e)[:200]}")

print(f"\nFinal: USDC={bal(NATIVE_USDC, dep):.2f}, pUSD={bal(PUSD, dep):.2f}")

# Sync CLOB
if proxy: _v2h._http_client = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True)
creds = ApiCreds(api_key=os.environ["API_KEY"], api_secret=os.environ["API_SECRET"],
                 api_passphrase=os.environ["API_PASSPHRASE"])
client = ClobClient(host="https://clob.polymarket.com", key=pk, chain_id=137, creds=creds,
                    signature_type=SIG_TYPE, funder=DEPOSIT)
params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=SIG_TYPE)
client.update_balance_allowance(params)
print(f"CLOB balance: {client.get_balance_allowance(params)}")

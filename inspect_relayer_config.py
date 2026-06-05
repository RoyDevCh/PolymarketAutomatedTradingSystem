import inspect
from py_builder_relayer_client.config import get_contract_config, ContractConfig
from py_builder_relayer_client.client import RelayClient
from py_builder_signing_sdk.config import BuilderConfig, BuilderApiKeyCreds
import os
from pathlib import Path

for line in Path("/home/roy/polymarket-arb/.env").read_text().splitlines():
    line = line.strip()
    if line.startswith("#") or not line or "=" not in line: continue
    k, _, v = line.partition("=")
    os.environ.setdefault(k.strip(), v.strip())

cfg = get_contract_config(137)
print("Relayer contract config:")
for f in cfg.__dict__ if hasattr(cfg, '__dict__') else dir(cfg):
    try:
        val = getattr(cfg, f)
        if not callable(val):
            print(f"  {f}: {val}")
    except: pass

# Try get_expected_deposit_wallet
try:
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
        private_key=os.environ["PRIVATE_KEY"],
        builder_config=builder_config,
    )
    print(f"\nExpected deposit wallet: {relayer.get_expected_deposit_wallet()}")
    print(f"Expected proxy wallet: {relayer.get_expected_proxy_wallet()}")
    print(f"Deposit deployed: {relayer.get_deployed(os.environ['DEPOSIT_WALLET'])}")
except Exception as e:
    print(f"Relayer error: {e}")

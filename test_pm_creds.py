"""Test Polymarket website API credential combinations."""
import os
from pathlib import Path
proxy_rc = Path.home() / ".proxyrc"
if proxy_rc.exists():
    for line in proxy_rc.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" in line and not line.startswith("#"):
            key, _, val = line.partition("=")
            if key.strip().lower().endswith("_proxy") and val.strip():
                os.environ.setdefault(key.strip(), val.strip())
import httpx
import py_clob_client_v2.http_helpers.helpers as _v2h
proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
if proxy:
    _v2h._http_client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True)
from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import ApiCreds, AssetType, BalanceAllowanceParams
KEY1 = "019e95bf-c366-7511-8930-284b2ca5239f"
KEY2 = "019e95e0-c64c-7bbc-9b23-54342ac1204e"
DEPOSIT = "0xAe886C5740F6614e0300BC2AF95e730f150685Ff"
env_path = Path("/home/roy/polymarket-arb/.env")
for line in env_path.read_text().splitlines():
    line = line.strip()
    if line.startswith("#") or not line or "=" not in line:
        continue
    key, _, val = line.partition("=")
    os.environ.setdefault(key.strip(), val.strip())
pk = os.environ.get("PRIVATE_KEY", "")
combos = [
    ("key1 KEY key2 SECRET key1 PASS", KEY1, KEY2, KEY1),
    ("key1 KEY key2 SECRET key2 PASS", KEY1, KEY2, KEY2),
    ("key2 KEY key1 SECRET key1 PASS", KEY2, KEY1, KEY1),
]
print("Testing API credential combinations...")
for name, api_key, api_secret, api_passphrase in combos:
    try:
        client = ClobClient(host="https://clob.polymarket.com", key=pk, chain_id=137,
            creds=ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase),
            signature_type=2, funder=DEPOSIT)
        if proxy:
            _v2h._http_client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True)
        bal = client.get_balance_allowance(params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        print(f"[OK] {name}: {bal}")
        break
    except Exception as e:
        print(f"[FAIL] {name}: {str(e)[:120]}")

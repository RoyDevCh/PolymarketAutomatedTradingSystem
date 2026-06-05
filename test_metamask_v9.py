"""Test all signature types + balance + deposit status."""
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

from eth_account import Account
import httpx
import py_clob_client_v2.http_helpers.helpers as _v2h

proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
if proxy:
    _v2h._http_client = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True)

from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import OrderArgs, OrderType

pk = os.environ["PRIVATE_KEY"]
eoa = Account.from_key(pk).address
DEPOSIT = os.environ.get("DEPOSIT_WALLET", "0x181242c978fb34c26068f8B154126F8Ea745C88B")

print(f"EOA: {eoa}")
print(f"Deposit: {DEPOSIT}")

# Get token
hc = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True) if proxy else httpx.Client(timeout=30.0)
markets = hc.get("https://gamma-api.polymarket.com/markets",
    params={"limit": 3, "active": "true", "closed": "false"}).json()
token = json.loads(markets[0]["clobTokenIds"])[0] if isinstance(markets[0]["clobTokenIds"], str) else markets[0]["clobTokenIds"][0]

# Derive creds with sig_type=1 (POLY_PROXY - common for MetaMask)
for derive_sig in [1, 2]:
    print(f"\n{'='*60}")
    print(f"Derive API key with signature_type={derive_sig}")
    print(f"{'='*60}")
    l1 = ClobClient(host="https://clob.polymarket.com", key=pk, chain_id=137,
                    signature_type=derive_sig, funder=DEPOSIT)
    if proxy: _v2h._http_client = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True)
    try:
        creds = l1.derive_api_key()
        print(f"API Key: {creds.api_key}")
    except Exception as e:
        print(f"derive failed: {e}")
        continue

    # Check balance with different params
    for sig in [derive_sig, 1, 2, 3]:
        client = ClobClient(host="https://clob.polymarket.com", key=pk, chain_id=137,
                            creds=creds, signature_type=sig, funder=DEPOSIT)
        if proxy: _v2h._http_client = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True)

        # Try balance
        for asset_type in ["COLLATERAL", "USDC", None]:
            try:
                if asset_type:
                    bal = client.get_balance_allowance(params={"asset_type": asset_type})
                else:
                    bal = client.get_balance_allowance()
                print(f"  sig={sig} balance({asset_type}): {bal}")
                break
            except TypeError:
                try:
                    from py_clob_client_v2.clob_types import BalanceAllowanceParams, AssetType
                    params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
                    bal = client.get_balance_allowance(params)
                    print(f"  sig={sig} balance(COLLATERAL): {bal}")
                    break
                except Exception as e2:
                    if asset_type is None:
                        print(f"  sig={sig} balance error: {str(e2)[:100]}")
            except Exception as e:
                if asset_type is None:
                    print(f"  sig={sig} balance error: {str(e)[:100]}")

        # Try order
        try:
            signed = client.create_order(OrderArgs(price=0.50, size=1.0, side="BUY", token_id=token))
            print(f"  sig={sig} order: maker={signed.maker} signer={signed.signer} sigType={signed.signatureType}")
            result = client.post_order(signed, OrderType.GTC)
            print(f"  *** ORDER SUCCESS: {result} ***")
            break
        except Exception as e:
            err = str(e)
            if "not allowed" in err:
                print(f"  sig={sig} order: maker not allowed")
            elif "signer" in err.lower():
                print(f"  sig={sig} order: signer mismatch")
            elif "balance" in err.lower() or "insufficient" in err.lower():
                print(f"  sig={sig} order: {err[:120]}")
            else:
                print(f"  sig={sig} order: {err[:120]}")

# Check Relayer deployed status
print(f"\n{'='*60}")
print("Relayer /deployed check")
print(f"{'='*60}")
relayer_key = os.environ.get("RELAYER_API_KEY", os.environ.get("API_KEY", ""))
relayer_addr = os.environ.get("RELAYER_API_KEY_ADDRESS", eoa)
headers = {"RELAYER_API_KEY": relayer_key, "RELAYER_API_KEY_ADDRESS": relayer_addr}
try:
    r = hc.get("https://relayer-v2.polymarket.com/deployed", params={"address": DEPOSIT}, headers=headers)
    print(f"Deposit deployed: {r.status_code} {r.text[:200]}")
except Exception as e:
    print(f"Relayer error: {e}")

print("\nDone.")

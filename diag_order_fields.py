"""Diagnose order maker/signer fields for different signature types."""
import os, sys, json, inspect
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

env_path = Path("/home/roy/polymarket-arb/.env")
for line in env_path.read_text().splitlines():
    line = line.strip()
    if line.startswith("#") or not line or "=" not in line: continue
    k, _, v = line.partition("=")
    os.environ.setdefault(k.strip(), v.strip())

import httpx
import py_clob_client_v2.http_helpers.helpers as _v2h
proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
if proxy:
    _v2h._http_client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True)

from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import OrderArgs, ApiCreds
from py_clob_client_v2.order_builder.builder import OrderBuilder

# Print SignatureTypeV2 enum
try:
    from py_clob_client_v2.clob_types import SignatureTypeV2
    print("SignatureTypeV2:")
    for name in dir(SignatureTypeV2):
        if not name.startswith("_"):
            print(f"  {name} = {getattr(SignatureTypeV2, name)}")
except Exception as e:
    print(f"SignatureTypeV2 error: {e}")

pk = os.environ["PRIVATE_KEY"]
DEPOSIT = os.environ.get("DEPOSIT_WALLET", "0x181242c978fb34c26068f8B154126F8Ea745C88B")

# Get a token
hc = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True) if proxy else httpx.Client(timeout=30.0)
resp = hc.get("https://gamma-api.polymarket.com/markets", params={"limit": 1, "active": "true"})
token = json.loads(resp.json()[0]["clobTokenIds"])[0] if isinstance(resp.json()[0]["clobTokenIds"], str) else resp.json()[0]["clobTokenIds"][0]

# Derive creds once
l1 = ClobClient(host="https://clob.polymarket.com", key=pk, chain_id=137, signature_type=2, funder=DEPOSIT)
if proxy: _v2h._http_client = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True)
creds = l1.derive_api_key()

for sig_type, name in [(0, "EOA"), (1, "POLY_PROXY"), (2, "POLY_NETWORK"), (3, "POLY_1271")]:
    print(f"\n=== sig_type={sig_type} ({name}) funder={DEPOSIT[:10]}... ===")
    try:
        client = ClobClient(host="https://clob.polymarket.com", key=pk, chain_id=137,
                            creds=creds, signature_type=sig_type, funder=DEPOSIT)
        if proxy: _v2h._http_client = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True)
        print(f"  builder.funder={client.builder.funder}")
        print(f"  builder.signature_type={client.builder.signature_type}")
        print(f"  signer.address()={client.signer.address()}")
        
        signed = client.create_order(OrderArgs(price=0.50, size=1.0, side="BUY", token_id=token))
        # Inspect signed order fields
        if hasattr(signed, "order"):
            o = signed.order
            for attr in ["maker", "signer", "signatureType", "tokenId", "makerAmount", "takerAmount"]:
                if hasattr(o, attr):
                    print(f"  order.{attr}={getattr(o, attr)}")
                elif isinstance(o, dict):
                    print(f"  order.{attr}={o.get(attr)}")
        elif hasattr(signed, "__dict__"):
            d = signed.__dict__
            for k in ["maker", "signer", "signatureType", "order"]:
                if k in d: print(f"  signed.{k}={d[k]}")
        else:
            print(f"  signed type={type(signed)} repr={str(signed)[:200]}")
    except Exception as e:
        print(f"  Error: {type(e).__name__}: {str(e)[:150]}")

# Check build_order source for maker logic
print("\n=== build_order maker logic (V2 section) ===")
src = inspect.getsource(OrderBuilder.build_order)
lines = src.split("\n")
in_v2 = False
for i, line in enumerate(lines):
    if "version == 2" in line or "OrderDataV2" in line:
        in_v2 = True
    if in_v2:
        if "maker" in line.lower() or "signer" in line.lower() or "signature" in line.lower():
            print(f"  {line.rstrip()}")

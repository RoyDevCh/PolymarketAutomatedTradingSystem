"""Derive API key for the deposit wallet (POLY_1271)"""
import os, sys
sys.path.insert(0, ".")
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

from core.config import CONFIG
from py_clob_client_v2 import ClobClient, SignatureTypeV2

FUNDER = "OLD_FUNDER_PLACEHOLDER"

# Create L1 client with POLY_1271 signature type
client = ClobClient(
    host=CONFIG.clob.api_url,
    chain_id=137,
    key=CONFIG.wallet.private_key,
    signature_type=SignatureTypeV2.POLY_1271,
    funder=FUNDER,
)

print(f"Signer address: {client.signer.address()}")
# funder is stored in client.builder, not client.funder
print(f"Builder funder: {client.builder.funder}")
print(f"Builder signature_type: {client.builder.signature_type}")
print(f"Mode: {client.mode}")

# Derive API key with this configuration
try:
    creds = client.derive_api_key()
    print(f"\nDerived API key: {creds.api_key}")
    print(f"API secret: {creds.api_secret[:10]}...")
    print(f"API passphrase: {creds.api_passphrase[:10]}...")
    print("\n=== UPDATE .env WITH THESE NEW CREDENTIALS ===")
    print(f"API_KEY={creds.api_key}")
    print(f"API_SECRET={creds.api_secret}")
    print(f"API_PASSPHRASE={creds.api_passphrase}")
except Exception as e:
    print(f"\nDerive API key error: {type(e).__name__}: {e}")
    
    # Try creating a new API key instead
    try:
        print("\nTrying create_api_key()...")
        creds = client.create_api_key()
        print(f"Created API key: {creds.api_key}")
        print(f"API secret: {creds.api_secret[:10]}...")
        print(f"API passphrase: {creds.api_passphrase[:10]}...")
    except Exception as e2:
        print(f"Create API key error: {type(e2).__name__}: {e2}")
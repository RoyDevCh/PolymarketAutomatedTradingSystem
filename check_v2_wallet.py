"""Check V2 signature types and wallet info"""
import os, sys
sys.path.insert(0, ".")

# Load proxy
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
proxy_url = os.environ.get("https_proxy") or os.environ.get("http_proxy")
if proxy_url:
    _v2h._http_client = httpx.Client(proxy=proxy_url, timeout=httpx.Timeout(30.0), follow_redirects=True)

from py_clob_client_v2 import SignatureTypeV2, ClobClient, ApiCreds
from core.config import CONFIG

# Signature types
print("=== SignatureTypeV2 ===")
for name in dir(SignatureTypeV2):
    if not name.startswith("_"):
        val = getattr(SignatureTypeV2, name)
        if not callable(val):
            print(f"  {name} = {val}")

# Create client with EOA (signature_type=0) and check
cfg = CONFIG.clob
wallet = CONFIG.wallet

print(f"\n=== Wallet Info ===")
print(f"Private key: {wallet.private_key[:8]}...{wallet.private_key[-4:]}")

client = ClobClient(
    host=cfg.api_url,
    chain_id=wallet.chain_id,
    key=wallet.private_key,
    creds=ApiCreds(
        api_key=cfg.api_key,
        api_secret=cfg.api_secret,
        api_passphrase=cfg.api_passphrase,
    ),
)

print(f"Signer address: {client.signer.address()}")
print(f"Client mode: {client.mode}")

# Check if Polymarket has a proxy address for this wallet
# Try derive_api_key to get address info
try:
    from py_clob_client_v2.http_helpers.helpers import get
    # Get the API key's associated address
    api_key_info = get(f"{cfg.api_url}/api-key")
    print(f"\nAPI key info: {api_key_info}")
except Exception as e:
    print(f"\nAPI key check error: {e}")

# Check if we need to use a proxy wallet (signature_type=1)
# The error "maker address not allowed" means our EOA is not a Polymarket deposit wallet
# We need to either:
# 1. Use signature_type=1 (POLY_PROXY) with a funder address
# 2. Or deposit funds to a Polymarket proxy wallet

# Let's check if our wallet has a proxy address
try:
    # In V1, we used create_api_key which might have given us a proxy wallet
    print(f"\n=== Checking deposit wallet ===")
    # The API key was created via create_api_key, which means we might have a deposit address
    wallet_addr = client.signer.address()
    print(f"Our wallet: {wallet_addr}")
    
    # Try to get the deposit address from the CLOB
    deposit_info = get(f"{cfg.api_url}/deposit-address?address={wallet_addr}")
    print(f"Deposit address: {deposit_info}")
except Exception as e:
    print(f"Deposit check error: {e}")
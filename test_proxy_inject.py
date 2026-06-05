"""Test proxy injection for CLOB client"""
import os, sys
sys.path.insert(0, ".")
from pathlib import Path

# Load proxy
proxyrc = Path.home() / ".proxyrc"
if proxyrc.exists():
    for line in proxyrc.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" in line and not line.startswith("#"):
            key, _, val = line.partition("=")
            if key.strip().lower().endswith("_proxy"):
                os.environ.setdefault(key.strip(), val.strip())

print(f"Proxy: {os.environ.get('https_proxy', 'NOT SET')}")

# Inject proxy
from core.clob_client import _inject_proxy_to_clob_client
_inject_proxy_to_clob_client()

import py_clob_client.http_helpers.helpers as h
print(f"Client type: {type(h._http_client)}")
print(f"Client: {h._http_client}")

from core.config import CONFIG
from py_clob_client.clob_types import ApiCreds
from py_clob_client.client import ClobClient

client = ClobClient(
    host=CONFIG.clob.api_url,
    key=CONFIG.wallet.private_key,
    chain_id=137,
    creds=ApiCreds(
        api_key=CONFIG.clob.api_key,
        api_secret=CONFIG.clob.api_secret,
        api_passphrase=CONFIG.clob.api_passphrase,
    ),
)

# Test: GET /time through proxied client
try:
    resp = h._http_client.get(f"{CONFIG.clob.api_url}/time")
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.text[:200]}")
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")

# Test: POST order (should work with proxy)
try:
    from py_clob_client.clob_types import OrderArgs
    # Get a token ID first
    markets_url = f"{CONFIG.clob.api_url}/markets"
    resp2 = h._http_client.get("https://gamma-api.polymarket.com/markets?active=true&limit=1")
    print(f"\nGamma API status: {resp2.status_code}")
except Exception as e:
    print(f"Gamma API Error: {type(e).__name__}: {e}")
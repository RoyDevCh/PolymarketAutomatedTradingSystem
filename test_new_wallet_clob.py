"""Test CLOB V2 API with the new wallet through JP-01 proxy."""
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

# Override with new wallet credentials BEFORE importing config
new_env = Path("/home/roy/polymarket-arb/wallet_new.env")
for line in new_env.read_text().splitlines():
    line = line.strip()
    if line.startswith("#") or not line:
        continue
    if "=" in line:
        key, _, val = line.partition("=")
        if key.strip() == "PRIVATE_KEY":
            os.environ["PRIVATE_KEY"] = val.strip()

from eth_account import Account

pk = os.environ.get("PRIVATE_KEY", "")
addr = Account.from_key(pk).address
print(f"Wallet: {addr}")
print(f"Private key: {pk[:10]}...")

# Create CLOB V2 client directly
from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import ApiCreds

host = "https://clob.polymarket.com"
chain_id = 137

print("\n=== Creating CLOB V2 Client ===")
client = ClobClient(host, key=pk, chain_id=chain_id)
print(f"Client created: {type(client).__name__}")

# Test: get markets
print("\n=== Getting Markets ===")
try:
    markets = client.get_markets()
    if isinstance(markets, list):
        print(f"Got {len(markets)} markets")
        if len(markets) > 0:
            m = markets[0]
            q = m.get("question", "?")[:80]
            print(f"  First market: {q}")
    elif isinstance(markets, dict):
        data = markets.get("data", markets)
        if isinstance(data, list):
            print(f"Got {len(data)} markets")
        else:
            print(f"Markets response: {str(markets)[:200]}")
except Exception as e:
    print(f"Error getting markets: {type(e).__name__}: {str(e)[:200]}")

# Test: create API key for the new wallet
print("\n=== Creating API Key ===")
try:
    result = client.create_api_key()
    print(f"Create API key result: {result}")
    if isinstance(result, dict):
        print(f"  API Key: {result.get('apiKey', result.get('api_key', 'N/A'))}")
        secret = result.get('apiSecret', result.get('api_secret', ''))
        passphrase = result.get('apiPassphrase', result.get('api_passphrase', ''))
        if secret:
            print(f"  API Secret: {secret[:8]}...")
        if passphrase:
            print(f"  API Passphrase: {passphrase[:8]}...")
except Exception as e:
    print(f"Create API key error: {type(e).__name__}: {str(e)[:200]}")

    # Try derive_api_key instead
    print("\n=== Trying derive_api_key ===")
    try:
        result2 = client.derive_api_key()
        print(f"Derive API key result: {result2}")
        if isinstance(result2, dict):
            print(f"  API Key: {result2.get('apiKey', result2.get('api_key', 'N/A'))}")
    except Exception as e2:
        print(f"Derive API key error: {type(e2).__name__}: {str(e2)[:200]}")

# Save API key to .env if found
print("\n=== Saving API Credentials ===")
env_path = Path("/home/roy/polymarket-arb/.env")
if env_path.exists():
    env_content = env_path.read_text()
    print(f"Current .env size: {len(env_content)} bytes")

print("\n=== Done ===")
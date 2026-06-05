"""Try to deploy deposit wallet via Polymarket Relayer API with different SSL/proxy configurations."""
import os, sys, json, time
sys.path.insert(0, ".")
from pathlib import Path

# Load proxy
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

from web3 import Web3
from eth_account import Account

# Load wallet credentials
new_env = Path("/home/roy/polymarket-arb/wallet_new.env")
for line in new_env.read_text().splitlines():
    line = line.strip()
    if line.startswith("#") or not line or "=" not in line:
        continue
    key, _, val = line.partition("=")
    if key.strip() == "PRIVATE_KEY":
        pk = val.strip()
    elif key.strip() == "WALLET_ADDRESS":
        addr = val.strip()
    elif key.strip() == "DEPOSIT_WALLET":
        deposit_wallet = val.strip()

# Also load API creds
env_path = Path("/home/roy/polymarket-arb/.env")
for line in env_path.read_text().splitlines():
    line = line.strip()
    if line.startswith("#") or not line or "=" not in line:
        continue
    key, _, val = line.partition("=")
    if key.strip() == "API_KEY":
        api_key = val.strip()
    elif key.strip() == "API_SECRET":
        api_secret = val.strip()
    elif key.strip() == "API_PASSPHRASE":
        api_passphrase = val.strip()

print(f"Wallet: {addr}")
print(f"Deposit Wallet: {deposit_wallet}")
print(f"API Key: {api_key}")

# Check deposit wallet status
w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
code = w3.eth.get_code(Web3.to_checksum_address(deposit_wallet))
print(f"Deposit wallet code: {len(code)} bytes ({'DEPLOYED' if len(code) > 0 else 'NOT DEPLOYED'})")

if len(code) > 0:
    print("\n[OK] Deposit wallet is already DEPLOYED!")
    sys.exit(0)

# Try multiple approaches to deploy via Relayer API
RELAYER_URL = "https://poly-relayer-api.polymarket.com"
proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")

print(f"\n{'='*60}")
print(f"  Attempting Deposit Wallet Deployment via Relayer API")
print(f"{'='*60}")

# Approach 1: Using py-clob-client-v2 with proper proxy injection
print("\n--- Approach 1: py-clob-client-v2 ---")
try:
    from py_clob_client_v2.client import ClobClient
    import httpx
    import py_clob_client_v2.http_helpers.helpers as _v2h
    
    # Inject proxy
    if proxy:
        _v2h._http_client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True, verify=True)
    
    client = ClobClient(
        host="https://clob.polymarket.com",
        key=pk,
        chain_id=137,
        creds=None,
    )
    
    # Try to create a deposit wallet via the client
    print("  Trying client methods...")
    for method_name in ["create_or_derive_api_creds", "derive_api_key", "create_api_key"]:
        if hasattr(client, method_name):
            try:
                result = getattr(client, method_name)()
                print(f"  {method_name}: {type(result).__name__} - {str(result)[:200]}")
            except Exception as e:
                err = str(e)[:150]
                print(f"  {method_name}: {type(e).__name__}: {err}")

except Exception as e:
    print(f"  Error: {type(e).__name__}: {str(e)[:200]}")

# Approach 2: Using py-builder-relayer-client
print("\n--- Approach 2: py-builder-relayer-client ---")
try:
    from py_builder_relayer_client.client import RelayClient
    
    # Inject proxy
    if proxy:
        import py_builder_relayer_client.http_helpers.helpers as _rh
        _rh._http_client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True, verify=True)
    
    relayer = RelayClient(
        relayer_url=RELAYER_URL,
        chain_id=137,
        private_key=pk,
    )
    
    # Get expected deposit wallet
    try:
        expected = relayer.get_expected_deposit_wallet()
        print(f"  Expected deposit wallet: {expected}")
    except Exception as e:
        print(f"  get_expected_deposit_wallet error: {type(e).__name__}: {str(e)[:150]}")
    
    # Try to deploy
    for method_name in ["deploy_deposit_wallet", "create_wallet", "create_deposit_wallet"]:
        if hasattr(relayer, method_name):
            try:
                result = getattr(relayer, method_name)()
                print(f"  {method_name}: {result}")
                # Check if deployed
                time.sleep(5)
                code = w3.eth.get_code(Web3.to_checksum_address(deposit_wallet))
                if len(code) > 0:
                    print(f"\n  [SUCCESS] Deposit wallet DEPLOYED! ({len(code)} bytes)")
                    sys.exit(0)
            except Exception as e:
                print(f"  {method_name}: {type(e).__name__}: {str(e)[:150]}")

except ImportError as e:
    print(f"  Import error: {e}")
except Exception as e:
    print(f"  Error: {type(e).__name__}: {str(e)[:200]}")

# Approach 3: Direct HTTP calls to Relayer API with different SSL settings
print("\n--- Approach 3: Direct HTTP calls ---")
import ssl
import urllib.request

headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://polymarket.com",
    "Referer": "https://polymarket.com",
}

# 3a: POST to /submit
payload = json.dumps({
    "type": "WALLET-CREATE",
    "from": addr,
    "to": "0x00000000000Fb5C9ADea0298D729A0CB3823Cc07",
}).encode()

for url_path in ["/submit", "/wallet-create", "/relay", "/v1/wallet/create"]:
    try:
        url = f"{RELAYER_URL}{url_path}"
        print(f"\n  Trying POST {url_path}...")
        
        # Try with proxy
        if proxy:
            proxy_handler = urllib.request.ProxyHandler({
                "http": proxy,
                "https": proxy,
            })
            opener = urllib.request.build_opener(proxy_handler)
        else:
            opener = urllib.request.build_opener()
        
        req = urllib.request.Request(url, data=payload, headers=headers)
        try:
            response = opener.open(req, timeout=15)
            result = response.read().decode()
            print(f"  Response ({response.status}): {result[:300]}")
            
            # Check if deployed
            time.sleep(3)
            code = w3.eth.get_code(Web3.to_checksum_address(deposit_wallet))
            if len(code) > 0:
                print(f"\n  [SUCCESS] Deposit wallet DEPLOYED! ({len(code)} bytes)")
                sys.exit(0)
        except urllib.error.HTTPError as e:
            print(f"  HTTP Error {e.code}: {e.read().decode()[:200]}")
        except Exception as e:
            print(f"  Error: {type(e).__name__}: {str(e)[:150]}")
            
            # Try with verify=False
            print(f"  Retrying with SSL verify=False...")
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                
                client = httpx.Client(
                    proxy=proxy,
                    timeout=httpx.Timeout(15.0),
                    follow_redirects=True,
                    verify=False,
                )
                resp = client.post(url, json=json.loads(payload.decode()), headers=headers)
                print(f"  Response ({resp.status_code}): {resp.text[:300]}")
                client.close()
            except Exception as e2:
                print(f"  Retry error: {type(e2).__name__}: {str(e2)[:150]}")

    except Exception as e:
        print(f"  URL error: {type(e).__name__}: {str(e)[:150]}")

# Approach 4: Try with requests library
print("\n--- Approach 4: requests library ---")
try:
    import requests
    session = requests.Session()
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    session.verify = False  # Skip SSL verification
    
    for url_path in ["/submit", "/wallet-create", "/v1/wallet/create"]:
        url = f"{RELAYER_URL}{url_path}"
        print(f"\n  Trying POST {url_path}...")
        try:
            resp = session.post(url, json=json.loads(payload.decode()), headers=headers, timeout=15)
            print(f"  Response ({resp.status_code}): {resp.text[:300]}")
            
            time.sleep(3)
            code = w3.eth.get_code(Web3.to_checksum_address(deposit_wallet))
            if len(code) > 0:
                print(f"\n  [SUCCESS] Deposit wallet DEPLOYED! ({len(code)} bytes)")
                sys.exit(0)
        except Exception as e:
            print(f"  Error: {type(e).__name__}: {str(e)[:150]}")
            
    session.close()
except ImportError:
    print("  requests not installed")
except Exception as e:
    print(f"  Error: {type(e).__name__}: {str(e)[:200]}")

# Approach 5: Try using the Polymarket CLOB API directly
print("\n--- Approach 5: Polymarket CLOB API ---")
try:
    import httpx
    if proxy:
        _v2h._http_client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True)
    
    # The deposit address endpoint might work
    for endpoint in [
        f"/deposit-address?address={addr}",
        f"/v1/deposit-address?address={addr}",
        f"/wallet?address={addr}",
    ]:
        try:
            resp = _v2h._http_client.get(f"https://clob.polymarket.com{endpoint}")
            print(f"  GET {endpoint}: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            print(f"  GET {endpoint}: {type(e).__name__}: {str(e)[:100]}")
    
    # Also try the gamma API
    for endpoint in [
        f"/deposit-address?address={addr}",
    ]:
        try:
            resp = _v2h._http_client.get(f"https://gamma-api.polymarket.com{endpoint}")
            print(f"  Gamma GET {endpoint}: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            print(f"  Gamma GET {endpoint}: {type(e).__name__}: {str(e)[:100]}")

except Exception as e:
    print(f"  Error: {type(e).__name__}: {str(e)[:200]}")

print(f"\n{'='*60}")
print("Deposit wallet deployment attempts completed.")
print(f"Deposit wallet status: {'DEPLOYED' if len(w3.eth.get_code(Web3.to_checksum_address(deposit_wallet))) > 0 else 'NOT DEPLOYED'}")
print(f"\nIf still not deployed, use ONE of these options:")
print(f"  A) Register at polymarket.com/developers for Builder API keys")
print(f"  B) Use Coinbase to connect to Polymarket (requires KYC)")
print(f"  C) Contact Polymarket support for manual deployment")
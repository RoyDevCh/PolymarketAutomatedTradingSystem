#!/usr/bin/env python3
"""Check CLOB balance and API key status"""
import os, sys
sys.path.insert(0, '/home/roy/polymarket-arb')
os.chdir('/home/roy/polymarket-arb')

# Load proxy
proxy_rc = os.path.expanduser('~/.proxyrc')
if os.path.exists(proxy_rc):
    for line in open(proxy_rc).read().splitlines():
        line = line.strip()
        if line.startswith('export '):
            line = line[len('export '):]
        if '=' in line and not line.startswith('#'):
            key, _, val = line.partition('=')
            key, val = key.strip(), val.strip()
            if key.lower().endswith('_proxy') and val:
                os.environ.setdefault(key, val)

os.environ.setdefault('HTTP_PROXY', 'http://127.0.0.1:7890')
os.environ.setdefault('HTTPS_PROXY', 'http://127.0.0.1:7890')

from dotenv import load_dotenv
load_dotenv('.env')

from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import ApiCreds, AssetType
import httpx
import py_clob_client_v2.http_helpers.helpers as h

host = os.getenv('CLOB_API_URL', 'https://clob.polymarket.com')
key = os.getenv('API_KEY', '')
secret = os.getenv('API_SECRET', '')
passphrase = os.getenv('API_PASSPHRASE', '')
private_key = os.getenv('PRIVATE_KEY', '')
funder = os.getenv('DEPOSIT_WALLET', '')
sig_type = int(os.getenv('SIGNATURE_TYPE', '3'))

print(f'API_KEY: {key[:8]}...{key[-4:]}')
print(f'host: {host}')
print(f'sig_type: {sig_type}')
print(f'funder: {funder[:10]}...{funder[-6:]}')

creds = ApiCreds(api_key=key, api_secret=secret, api_passphrase=passphrase)
client = ClobClient(
    host=host,
    key=private_key,
    chain_id=137,
    signature_type=sig_type,
    funder=funder,
    creds=creds,
)

# Inject proxy
h._http_client = httpx.Client(proxy='http://127.0.0.1:7890', timeout=httpx.Timeout(30.0), follow_redirects=True)
print(f'Proxy injected')

# Test basic API
import time
print(f'\n=== CLOB API Tests ===')

t0 = time.time()
try:
    t = client.get_ok()
    print(f'CLOB time: {t} ({time.time()-t0:.1f}s)')
except Exception as e:
    print(f'CLOB time error: {e}')

# Balance
t0 = time.time()
try:
    client.update_balance_allowance(params=AssetType.COLLATERAL)
    print(f'Update balance: OK ({time.time()-t0:.1f}s)')
except Exception as e:
    print(f'Update balance error: {e}')

t0 = time.time()
try:
    bal = client.get_balance_allowance(params=AssetType.COLLATERAL)
    print(f'Balance: {bal} ({time.time()-t0:.1f}s)')
except Exception as e:
    print(f'Balance error: {e}')
    # Try raw
    import requests
    try:
        r = requests.get(
            f'{host}/balance-allowance',
            params={'signature_type': '3', 'asset_type': 'COLLATERAL'},
            proxies={'https': 'http://127.0.0.1:7890', 'http': 'http://127.0.0.1:7890'},
            timeout=10,
        )
        print(f'Raw balance response: {r.status_code} {r.text[:200]}')
    except Exception as e2:
        print(f'Raw balance error: {e2}')

# Test order API (just connectivity, not actually placing)
print(f'\n=== Geoblock Check ===')
try:
    import requests
    r = requests.get('https://polymarket.com/api/geoblock', 
                      proxies={'https': 'http://127.0.0.1:7890', 'http': 'http://127.0.0.1:7890'},
                      timeout=10)
    print(f'Geoblock: {r.text[:150]}')
except Exception as e:
    print(f'Geoblock error: {e}')
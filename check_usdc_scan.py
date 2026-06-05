"""Check USDC transfers via PolygonScan API."""
import httpx
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

proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(15.0), follow_redirects=True)

# Check our EOA
addr = "0xE56A44444F55aD30C87235f7C94786509881Da3A"
USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
url = f"https://api.polygonscan.com/api?module=account&action=tokentx&address={addr}&contractaddress={USDC}&sort=desc&apikey=YourApiKeyToken"
resp = client.get(url, timeout=15)
data = resp.json()
if data.get("status") == "1":
    txs = data.get("result", [])
    print(f"USDC transactions for our EOA: {len(txs)}")
    for tx in txs[:10]:
        from_a = tx.get("from", "")
        to_a = tx.get("to", "")
        value = int(tx.get("value", "0")) / 1e6
        block = tx.get("blockNumber", "")
        print(f"  Block {block}: {from_a[:12]}... -> {to_a[:12]}...  {value:.2f}")
else:
    print(f"API: {data.get('message', 'unknown')}")

# Check Polymarket deposit address
pm = "0xAe886C5740F6614e0300BC2AF95e730f150685Ff"
url2 = f"https://api.polygonscan.com/api?module=account&action=tokentx&address={pm}&contractaddress={USDC}&sort=desc&apikey=YourApiKeyToken"
resp2 = client.get(url2, timeout=15)
data2 = resp2.json()
if data2.get("status") == "1":
    txs2 = data2.get("result", [])
    print(f"\nUSDC transactions for PM deposit: {len(txs2)}")
    for tx in txs2[:10]:
        from_a = tx.get("from", "")
        to_a = tx.get("to", "")
        value = int(tx.get("value", "0")) / 1e6
        block = tx.get("blockNumber", "")
        print(f"  Block {block}: {from_a[:12]}... -> {to_a[:12]}...  {value:.2f}")
else:
    print(f"\nPM deposit API: {data2.get('message', 'unknown')}")

# Check Polymarket API address
api_addr = "0x6b1fda796ffdd756d06cf20ce43f3c8a172e60ee"
url3 = f"https://api.polygonscan.com/api?module=account&action=tokentx&address={api_addr}&contractaddress={USDC}&sort=desc&apikey=YourApiKeyToken"
resp3 = client.get(url3, timeout=15)
data3 = resp3.json()
if data3.get("status") == "1":
    txs3 = data3.get("result", [])
    print(f"\nUSDC transactions for PM API addr: {len(txs3)}")
    for tx in txs3[:10]:
        from_a = tx.get("from", "")
        to_a = tx.get("to", "")
        value = int(tx.get("value", "0")) / 1e6
        block = tx.get("blockNumber", "")
        print(f"  Block {block}: {from_a[:12]}... -> {to_a[:12]}...  {value:.2f}")

client.close()
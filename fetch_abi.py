"""Fetch contract ABI from Polygonscan."""
import os, httpx, json
from pathlib import Path

proxy_rc = Path.home() / ".proxyrc"
if proxy_rc.exists():
    for line in proxy_rc.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "): line = line[len("export "):]
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            if k.strip().lower().endswith("_proxy") and v.strip():
                os.environ.setdefault(k.strip(), v.strip())

proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
client = httpx.Client(proxy=proxy, timeout=20.0, follow_redirects=True)

addrs = {
    "pUSD_impl": "0x6bBCef9f7ef3B6C592c99e0f206a0DE94Ad0925f",
    "deposit_impl": "0x58CA52ebe0DadfdF531Cde7062e76746de4Db1eB",
}

for name, addr in addrs.items():
    url = f"https://api.polygonscan.com/api?module=contract&action=getabi&address={addr}&apikey=YourApiKeyToken"
    try:
        r = client.get(url)
        data = r.json()
        if data.get("status") == "1":
            abi = json.loads(data["result"])
            fns = [x["name"] for x in abi if x.get("type") == "function"]
            print(f"\n{name} ({addr}):")
            print(f"  Functions: {fns[:30]}")
            # Show deposit-related
            for x in abi:
                if x.get("type") == "function" and any(k in x["name"].lower() for k in ["deposit", "mint", "convert", "wrap", "approve", "swap", "collateral"]):
                    print(f"  -> {x['name']}: inputs={[i['type'] for i in x.get('inputs',[])]}")
        else:
            print(f"{name}: API error {data.get('message')} {str(data.get('result',''))[:100]}")
    except Exception as e:
        print(f"{name}: {e}")

client.close()

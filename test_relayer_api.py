import httpx, os
proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
if not proxy:
    from pathlib import Path
    proxyrc = Path.home() / ".proxyrc"
    if proxyrc.exists():
        for line in proxyrc.read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export "):]
            if "=" in line and not line.startswith("#"):
                key, _, val = line.partition("=")
                if key.strip().lower().endswith("_proxy") and val.strip():
                    proxy = val.strip()
                    break

print(f"Proxy: {proxy}")

client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(15.0))

# Try relayer API
payload = {
    "type": "WALLET-CREATE",
    "from": "0xE56A44444F55aD30C87235f7C94786509881Da3A",
    "to": "0x00000000000Fb5C9ADea0298D729A0CB3823Cc07",
}

print(f"Sending WALLET-CREATE to Polymarket Relayer...")
try:
    resp = client.post(
        "https://poly-relayer-api.polymarket.com/submit",
        json=payload,
        headers={"Content-Type": "application/json"},
    )
    print(f"Status: {resp.status_code}")
    print(f"Body: {resp.text[:500]}")
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")

# Also try the deposit address endpoint
print(f"\nTrying deposit-address endpoint...")
try:
    resp2 = client.get(
        f"https://poly-relayer-api.polymarket.com/deposit-address?address=0xE56A44444F55aD30C87235f7C94786509881Da3A",
        headers={"Content-Type": "application/json"},
    )
    print(f"Status: {resp2.status_code}")
    print(f"Body: {resp2.text[:500]}")
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")

client.close()
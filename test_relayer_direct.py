"""Test relayer API connectivity"""
import httpx, os
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
print(f"Proxy: {proxy}")

# Test 1: No proxy
print("\nTest 1: Direct connection (no proxy)")
try:
    client = httpx.Client(timeout=httpx.Timeout(10.0))
    r = client.get("https://poly-relayer-api.polymarket.com/time", timeout=10)
    print(f"  Status: {r.status_code}")
    print(f"  Body: {r.text[:200]}")
    client.close()
except Exception as e:
    print(f"  Error: {type(e).__name__}: {str(e)[:150]}")

# Test 2: Through proxy (Polymarket group)
print(f"\nTest 2: Through proxy ({proxy})")
try:
    client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(15.0), follow_redirects=True)
    
    # Test time endpoint first
    try:
        r = client.get("https://poly-relayer-api.polymarket.com/time", timeout=10)
        print(f"  GET /time: {r.status_code} {r.text[:50]}")
    except Exception as e:
        print(f"  GET /time error: {type(e).__name__}: {str(e)[:100]}")
    
    # Test deposit-address
    try:
        r = client.get(
            "https://poly-relayer-api.polymarket.com/deposit-address?address=0xE56A44444F55aD30C87235f7C94786509881Da3A",
            timeout=10,
        )
        print(f"  GET /deposit-address: {r.status_code}")
        print(f"  Body: {r.text[:300]}")
    except Exception as e:
        print(f"  GET /deposit-address error: {type(e).__name__}: {str(e)[:100]}")
    
    # Test WALLET-CREATE
    try:
        r = client.post(
            "https://poly-relayer-api.polymarket.com/submit",
            json={
                "type": "WALLET-CREATE",
                "from": "0xE56A44444F55aD30C87235f7C94786509881Da3A",
                "to": "0x00000000000Fb5C9ADea0298D729A0CB3823Cc07",
            },
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        print(f"  POST /submit (WALLET-CREATE): {r.status_code}")
        print(f"  Body: {r.text[:300]}")
    except Exception as e:
        print(f"  POST /submit error: {type(e).__name__}: {str(e)[:100]}")
    
    client.close()
except Exception as e:
    print(f"  Proxy error: {type(e).__name__}: {e}")

# Test 3: Direct connection to relayer (no proxy)
print(f"\nTest 3: Direct to relayer (no proxy)")
try:
    client = httpx.Client(timeout=httpx.Timeout(10.0))
    r = client.post(
        "https://poly-relayer-api.polymarket.com/submit",
        json={
            "type": "WALLET-CREATE",
            "from": "0xE56A44444F55aD30C87235f7C94786509881Da3A",
            "to": "0x00000000000Fb5C9ADea0298D729A0CB3823Cc07",
        },
        headers={"Content-Type": "application/json"},
    )
    print(f"  Status: {r.status_code}")
    print(f"  Body: {r.text[:300]}")
    client.close()
except Exception as e:
    print(f"  Error: {type(e).__name__}: {str(e)[:150]}")
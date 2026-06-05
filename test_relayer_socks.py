import httpx

# Try SOCKS5 proxy (port 7891) for relayer API
for proxy_url in ["socks5://127.0.0.1:7891", "http://127.0.0.1:7890"]:
    print(f"\nTesting with proxy: {proxy_url}")
    try:
        client = httpx.Client(proxy=proxy_url, timeout=httpx.Timeout(15.0))
        
        # Test WALLET-CREATE
        r = client.post(
            "https://poly-relayer-api.polymarket.com/submit",
            json={
                "type": "WALLET-CREATE",
                "from": "0xE56A44444F55aD30C87235f7C94786509881Da3A",
                "to": "0x00000000000Fb5C9ADea0298D729A0CB3823Cc07",
            },
            headers={"Content-Type": "application/json"},
        )
        print(f"  WALLET-CREATE Status: {r.status_code}")
        print(f"  Body: {r.text[:300]}")
        
        # Test deposit-address
        r2 = client.get(
            "https://poly-relayer-api.polymarket.com/deposit-address?address=0xE56A44444F55aD30C87235f7C94786509881Da3A",
            headers={"Content-Type": "application/json"},
        )
        print(f"  deposit-address Status: {r2.status_code}")
        print(f"  Body: {r2.text[:300]}")
        
        client.close()
        break  # If we got here, it worked
    except Exception as e:
        print(f"  Error: {type(e).__name__}: {str(e)[:200]}")
        try:
            client.close()
        except:
            pass
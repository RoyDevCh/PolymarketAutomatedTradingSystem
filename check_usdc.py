"""Check USDC balance specifically"""
import os, asyncio, aiohttp, json
from pathlib import Path
proxyrc = Path.home() / ".proxyrc"
if proxyrc.exists():
    for line in proxyrc.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" in line:
            key, _, val = line.partition("=")
            if key.strip().lower().endswith("_proxy"):
                os.environ.setdefault(key.strip(), val.strip())

async def check_usdc():
    proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
    addr = "0x43083C461fc9b875c97032f375bf8aef81681B8e"
    
    # USDC on Polygon: 0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174
    # USDC.e (bridged): 0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174
    # Native USDC: 0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359
    
    for name, contract in [
        ("USDC.e (bridged)", "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"),
        ("USDC (native)", "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"),
    ]:
        payload = {
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [{
                "to": contract,
                "data": f"0x70a08231{addr[2:].lower().zfill(64)}"
            }, "latest"],
            "id": 1
        }
        
        for rpc in ["https://polygon-bor-rpc.publicnode.com"]:
            try:
                async with aiohttp.ClientSession(trust_env=True) as s:
                    async with s.post(rpc, json=payload, proxy=proxy, timeout=aiohttp.ClientTimeout(total=10)) as r:
                        data = json.loads(await r.text())
                        if "result" in data and data["result"] != "0x":
                            raw = int(data["result"], 16)
                            # USDC has 6 decimals
                            balance = raw / 1e6
                            print(f"{name}: {balance:.2f} USDC")
                            if balance > 0:
                                return balance
                        elif "error" in data:
                            print(f"{name}: RPC error - {data['error'].get('message', 'unknown')[:60]}")
            except Exception as e:
                print(f"{name}: {type(e).__name__}")
    
    # Also check via Polygonscan
    print("\nTrying Polygonscan API...")
    try:
        async with aiohttp.ClientSession(trust_env=True) as s:
            # POL balance
            url = f"https://api.polygonscan.com/api?module=account&action=balance&address={addr}&tag=latest"
            async with s.get(url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json(content_type=None)
                if data.get("status") == "1":
                    bal = int(data["result"]) / 1e18
                    print(f"POL: {bal:.4f}")
            
            # USDC.e
            url2 = f"https://api.polygonscan.com/api?module=account&action=tokenbalance&contractaddress=0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174&address={addr}&tag=latest"
            async with s.get(url2, proxy=proxy, timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json(content_type=None)
                if data.get("status") == "1":
                    usdc = int(data["result"]) / 1e6
                    print(f"USDC.e: {usdc:.2f}")
            
            # Native USDC
            url3 = f"https://api.polygonscan.com/api?module=account&action=tokenbalance&contractaddress=0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359&address={addr}&tag=latest"
            async with s.get(url3, proxy=proxy, timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json(content_type=None)
                if data.get("status") == "1":
                    usdc_n = int(data["result"]) / 1e6
                    print(f"USDC: {usdc_n:.2f}")
    except Exception as e:
        print(f"Polygonscan error: {type(e).__name__}: {e}")

asyncio.run(check_usdc())
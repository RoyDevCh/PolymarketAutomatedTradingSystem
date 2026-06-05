"""Check wallet balance via Polymarket CLOB API"""
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

from core.config import CONFIG
from py_clob_client.client import ClobClient

async def check():
    proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
    addr = "0x43083C461fc9b875c97032f375bf8aef81681B8e"
    
    print(f"Wallet: {addr}")
    print()
    
    # 1. Check via Polymarket CLOB API
    try:
        client = ClobClient(
            host=CONFIG.clob.api_url,
            key=CONFIG.wallet.private_key,
            chain_id=137,
            creds=None,  # L1 only for checking
        )
        
        # Get API keys (already created)
        try:
            creds = client.derive_api_key()
            print(f"API Key: {creds.api_key[:16]}... (VALID)")
        except Exception as e:
            print(f"API Key check: {e}")
    except Exception as e:
        print(f"CLOB Client error: {e}")
    
    # 2. Check POL balance via Polygon RPC through proxy
    print("\nChecking on-chain balance...")
    payload = {"jsonrpc": "2.0", "method": "eth_getBalance", "params": [addr, "latest"], "id": 1}
    
    # Try multiple RPCs
    rpcs = [
        "https://polygon-bor-rpc.publicnode.com",
        "https://rpc.ankr.com/polygon",
        "https://polygon-mainnet.public.blastapi.io",
        "https://polygon.drpc.org",
        "https://1rpc.io/matic",
    ]
    
    for rpc in rpcs:
        try:
            async with aiohttp.ClientSession(trust_env=True) as s:
                async with s.post(rpc, json=payload, proxy=proxy, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    text = await r.text()
                    try:
                        data = json.loads(text)
                        if "result" in data:
                            bal_wei = int(data["result"], 16)
                            bal_pol = bal_wei / 1e18
                            print(f"POL Balance: {bal_pol:.4f} POL (via {rpc[:40]}...)")
                            print(f"Approx USD: ~${bal_pol * 0.19:.2f}")
                            break
                        else:
                            print(f"  {rpc[:40]}... error: {data.get('error', {}).get('message', 'unknown')[:80]}")
                    except json.JSONDecodeError:
                        print(f"  {rpc[:40]}... non-JSON response")
        except Exception as e:
            print(f"  {rpc[:40]}... failed: {type(e).__name__}")
    
    # 3. Check .env config summary
    print(f"\n.Configuration Summary:")
    print(f"  PRIVATE_KEY: {CONFIG.wallet.private_key[:8]}...{CONFIG.wallet.private_key[-4:]}")
    print(f"  API_KEY:     {CONFIG.clob.api_key[:16]}...")
    print(f"  API_SECRET:  {CONFIG.clob.api_secret[:8]}...")
    print(f"  API_PASS:    {CONFIG.clob.api_passphrase[:8]}...")
    print(f"  RPC_URL:     {CONFIG.wallet.rpc_url[:50]}...")

asyncio.run(check())
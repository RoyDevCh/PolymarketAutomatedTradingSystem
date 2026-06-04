import asyncio, os, sys
sys.path.insert(0, ".")
os.environ.setdefault("https_proxy", "http://127.0.0.1:7890")
os.environ.setdefault("http_proxy", "http://127.0.0.1:7890")

from pathlib import Path
proxyrc = Path.home() / ".proxyrc"
if proxyrc.exists():
    for line in proxyrc.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" in line and not line.startswith("#"):
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if key.lower().endswith("_proxy") and val:
                os.environ.setdefault(key, val)

from core.mdg import MarketDataGateway

async def test():
    mdg = MarketDataGateway(snapshot_callback=lambda s: None)
    markets = await mdg.discover_markets()
    print(f"Discovered {len(markets)} markets")
    for m in markets[:10]:
        print(f"  Vol=${m.volume:,.2f}  Liq=${m.liquidity:,.2f}  Q={m.question[:60]}")
        print(f"    YES={m.yes_token_id[:30]}...")
        print(f"    NO ={m.no_token_id[:30]}...")

asyncio.run(test())
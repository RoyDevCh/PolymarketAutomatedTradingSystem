import asyncio, aiohttp, json, os
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

async def check():
    proxy = os.environ.get("https_proxy")
    conn = aiohttp.TCPConnector()
    async with aiohttp.ClientSession(connector=conn, trust_env=True) as s:
        url = "https://gamma-api.polymarket.com/markets?active=true&closed=false&order=volume&ascending=false&limit=3"
        async with s.get(url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=15)) as r:
            markets = await r.json()
            
            for m in markets:
                q = m.get("question", "")[:60]
                clob_ids = m.get("clobTokenIds", [])
                if isinstance(clob_ids, str):
                    clob_ids = json.loads(clob_ids)
                outcomes = m.get("outcomes", [])
                if isinstance(outcomes, str):
                    outcomes = json.loads(outcomes)
                
                print("\n" + "=" * 70)
                print("Market: " + q)
                print("outcomes: " + str(outcomes))
                
                yes_ask = None
                no_ask = None
                yes_bid = None
                no_bid = None
                
                for i, tid in enumerate(clob_ids[:2]):
                    label = outcomes[i] if i < len(outcomes) else ("YES" if i == 0 else "NO")
                    book_url = "https://clob.polymarket.com/book?token_id=" + tid
                    try:
                        async with s.get(book_url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=5)) as br:
                            if br.status == 200:
                                book = await br.json()
                                asks = book.get("asks", [])
                                bids = book.get("bids", [])
                                ba = float(asks[0]["price"]) if asks else 0
                                bb = float(bids[0]["price"]) if bids else 0
                                print("  " + label + " token:")
                                print("    Best Bid: " + str(bb) + "  Best Ask: " + str(ba))
                                print("    Top 3 Asks: " + str([(a["price"], a["size"]) for a in asks[:3]]))
                                print("    Top 3 Bids: " + str([(b["price"], b["size"]) for b in bids[:3]]))
                                if label.upper() == "YES":
                                    yes_ask = ba
                                    yes_bid = bb
                                else:
                                    no_ask = ba
                                    no_bid = bb
                    except Exception as e:
                        print("  " + label + " token: ERROR " + str(e))
                
                if yes_ask and no_ask:
                    total = yes_ask + no_ask
                    spread = 1.0 - total
                    print("\n  ARB CHECK: Yes_Ask=" + str(yes_ask) + " + No_Ask=" + str(no_ask) + " = " + str(round(total, 4)))
                    print("  Spread (1 - total): " + str(round(spread, 4)))
                    if spread > 0:
                        print("  *** ARBITRAGE OPPORTUNITY ***")

asyncio.run(check())
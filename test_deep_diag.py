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

async def fetch_book(session, token_id, proxy):
    """Fetch orderbook for one token"""
    url = "https://clob.polymarket.com/book?token_id=" + token_id
    try:
        async with session.get(url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=5)) as r:
            if r.status == 200:
                return await r.json()
    except:
        pass
    return None

async def main():
    proxy = os.environ.get("https_proxy")
    conn = aiohttp.TCPConnector()
    async with aiohttp.ClientSession(connector=conn, trust_env=True) as s:
        # Scan 3 tiers: low volume, medium volume, high volume
        for tier, order, asc, label in [
            ("low", "volume", True, "LOW VOLUME (arb likely)"),
            ("mid", "volume", False, "MID VOLUME"),
            ("high", "volume", False, "HIGH VOLUME (arb unlikely)"),
        ]:
            limit = 15 if tier == "low" else 5
            url = f"https://gamma-api.polymarket.com/markets?active=true&closed=false&order={order}&ascending={'true' if asc else 'false'}&limit={limit}"
            
            async with s.get(url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=15)) as r:
                markets = await r.json()
            
            print(f"\n{'='*80}")
            print(f"  TIER: {label} ({len(markets)} markets)")
            print(f"{'='*80}")
            
            arb_count = 0
            near_miss = 0
            
            for m in markets[:10]:
                clob_ids = m.get("clobTokenIds", [])
                if isinstance(clob_ids, str):
                    clob_ids = json.loads(clob_ids)
                outcomes = m.get("outcomes", [])
                if isinstance(outcomes, str):
                    outcomes = json.loads(outcomes)
                if len(clob_ids) < 2:
                    continue
                
                q = m.get("question", "")[:50]
                vol = float(m.get("volumeNum", 0) or m.get("volume", 0))
                
                # Fetch both books concurrently
                book1 = await fetch_book(s, clob_ids[0], proxy)
                book2 = await fetch_book(s, clob_ids[1], proxy)
                
                if not book1 or not book2:
                    print(f"  {q}: BOOK FETCH FAILED")
                    continue
                
                asks1 = book1.get("asks", [])
                bids1 = book1.get("bids", [])
                asks2 = book2.get("asks", [])
                bids2 = book2.get("bids", [])
                
                yes_label = outcomes[0] if len(outcomes) > 0 else "T1"
                no_label = outcomes[1] if len(outcomes) > 1 else "T2"
                
                yes_ask = float(asks1[0]["price"]) if asks1 else None
                no_ask = float(asks2[0]["price"]) if asks2 else None
                yes_bid = float(bids1[0]["price"]) if bids1 else None
                no_bid = float(bids2[0]["price"]) if bids2 else None
                
                # VWAP: buying $2 through each book
                def calc_vwap(asks, budget):
                    if not asks:
                        return None, 0, 0
                    remain = budget
                    total_shares = 0
                    total_cost = 0
                    for a in asks[:20]:
                        p = float(a["price"])
                        sz = float(a["size"])
                        cost = p * sz
                        if cost <= remain:
                            total_shares += sz
                            total_cost += cost
                            remain -= cost
                        else:
                            shares = remain / p
                            total_shares += shares
                            total_cost += remain
                            remain = 0
                            break
                    vwap = total_cost / total_shares if total_shares > 0 else None
                    return vwap, total_shares, total_cost
                
                vwap_yes, sz_yes, cost_yes = calc_vwap(asks1, 2.0)
                vwap_no, sz_no, cost_no = calc_vwap(asks2, 2.0)
                
                # Calculate results
                if yes_ask and no_ask:
                    total = yes_ask + no_ask
                    spread = 1.0 - total
                    
                    if vwap_yes and vwap_no:
                        vwap_total = vwap_yes + vwap_no
                        vwap_spread = 1.0 - vwap_total
                        min_size = min(sz_yes, sz_no)
                        profit_per_unit = 1.0 - vwap_total
                        profit_dollar = profit_per_unit * min_size
                        
                        marker = ""
                        if vwap_spread > 0:
                            marker = " *** ARBITRAGE ***"
                            arb_count += 1
                        elif vwap_spread > -0.02:
                            marker = " (near-miss)"
                            near_miss += 1
                        
                        print(f"\n  {q}  Vol=${vol:,.0f}")
                        print(f"    {yes_label}: bid={yes_bid} ask={yes_ask} depth={len(asks1)} VWAP=${vwap_yes:.4f} buy${sz_yes:.2f}shares/${cost_yes:.2f}")
                        print(f"    {no_label}: bid={no_bid} ask={no_ask} depth={len(asks2)} VWAP=${vwap_no:.4f} buy${sz_no:.2f}shares/${cost_no:.2f}")
                        print(f"    BBO_SUM={total:.4f} VWAP_SUM={vwap_total:.4f} Spread={spread:+.4f} VWAP_Spread={vwap_spread:+.4f} Profit=${profit_dollar:.4f}{marker}")
                    else:
                        print(f"  {q}  Vol=${vol:,.0f}  BBO_SUM={total:.4f} Spread={spread:+.4f} (insufficient depth for VWAP)")
                else:
                    print(f"  {q}  Vol=${vol:,.0f}  (one-sided book, no arb)")
            
            print(f"\n  --> {tier}: {arb_count} arbs, {near_miss} near-misses found")

asyncio.run(main())
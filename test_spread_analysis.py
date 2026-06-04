"""
Phase 2 增强版 - BBO 诊断 + 套利扫描
输出每个市场的 BBO 和深度情况，即使没有套利也可见
"""
import asyncio, os, sys
sys.path.insert(0, ".")
from pathlib import Path

# Load proxy
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

from core.config import CONFIG
from core.mdg import MarketDataGateway
from core.spe import StrategyPricingEngine
from core.models import OrderBookSnapshot, PriceLevel, MarketInfo
import aiohttp, json


async def main():
    proxy = os.environ.get("https_proxy")
    conn = aiohttp.TCPConnector()
    market_data = []

    # Discover markets
    mdg = MarketDataGateway(snapshot_callback=lambda s: None)
    markets = await mdg.discover_markets()
    print(f"\nDiscovering {len(markets)} markets, fetching orderbooks for top 30...")
    print("=" * 90)
    print(f"{'Market':<50} {'Yes_Ask':>8} {'No_Ask':>8} {'Sum':>7} {'Spread':>7} {'Arb?':>5} {'Depth':>7}")
    print("-" * 90)

    arb_count = 0
    checked = 0

    async with aiohttp.ClientSession(connector=conn, trust_env=True) as s:
        for m in markets[:30]:
            clob_ids = [m.yes_token_id, m.no_token_id]
            yes_ask = no_ask = yes_bid = no_bid = None
            y_depth = n_depth = 0
            y_depth_usd = n_depth_usd = 0.0

            for i, tid in enumerate(clob_ids):
                try:
                    url = f"https://clob.polymarket.com/book?token_id={tid}"
                    async with s.get(url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=5)) as r:
                        if r.status == 200:
                            book = await r.json()
                            asks = book.get("asks", [])
                            bids = book.get("bids", [])
                            if asks:
                                price = float(asks[0]["price"])
                                depth_usd = sum(float(a["price"]) * float(a["size"]) for a in asks[:5])
                            else:
                                price = None
                                depth_usd = 0
                            bid_p = float(bids[0]["price"]) if bids else None
                            depth = min(len(asks), len(bids))

                            if i == 0:
                                yes_ask = price
                                yes_bid = bid_p
                                y_depth = len(asks)
                                y_depth_usd = depth_usd
                            else:
                                no_ask = price
                                no_bid = bid_p
                                n_depth = len(asks)
                                n_depth_usd = depth_usd
                except Exception:
                    pass

            if yes_ask is not None and no_ask is not None:
                total = yes_ask + no_ask
                spread = 1.0 - total
                arb = "YES" if spread > 0 else ""
                q = m.question[:48]
                checked += 1

                # VWAP calc
                budget = 2.0
                
                def calc_vwap(asks_list, budget_usd):
                    if not asks_list:
                        return None, 0, 0
                    remain = budget_usd
                    shares = cost = 0.0
                    best_p = float(asks_list[0]["price"])
                    for a in asks_list[:20]:
                        p, sz = float(a["price"]), float(a["size"])
                        c = p * sz
                        if c <= remain:
                            shares += sz
                            cost += c
                            remain -= c
                        else:
                            sh = remain / p
                            shares += sh
                            cost += remain
                            remain = 0
                            break
                    vwap = cost / shares if shares > 0 else best_p
                    slip = (vwap - best_p) * shares if shares > 0 else 0
                    return vwap, shares, slip

                # Re-fetch books for VWAP
                yes_asks = no_asks = []
                try:
                    async with s.get(f"https://clob.polymarket.com/book?token_id={clob_ids[0]}", proxy=proxy, timeout=aiohttp.ClientTimeout(total=5)) as r:
                        if r.status == 200:
                            yes_asks = (await r.json()).get("asks", [])
                    async with s.get(f"https://clob.polymarket.com/book?token_id={clob_ids[1]}", proxy=proxy, timeout=aiohttp.ClientTimeout(total=5)) as r:
                        if r.status == 200:
                            no_asks = (await r.json()).get("asks", [])
                except:
                    pass

                vw_y, sz_y, sl_y = calc_vwap(yes_asks, budget)
                vw_n, sz_n, sl_n = calc_vwap(no_asks, budget)

                if vw_y and vw_n:
                    vwap_sum = vw_y + vw_n
                    vwap_spread = 1.0 - vwap_sum
                    arb = "YES" if vwap_spread > 0 else ""
                    min_sz = min(sz_y, sz_n)
                    profit = min_sz * vwap_spread if vwap_spread > 0 else vwap_spread * min_sz

                    print(f"{q:<50} {vw_y:>8.4f} {vw_n:>8.4f} {vwap_sum:>7.4f} {vwap_spread:>+7.4f} {arb:>5} yd={y_depth}/{n_depth}")

                    if vwap_spread > 0:
                        arb_count += 1
                        print(f"  >>> ARBITRAGE: Buy YES@{vw_y:.4f} + Buy NO@{vw_n:.4f} = {vwap_sum:.4f}, profit=${profit:.4f} per round, size={min_sz:.2f} shares")
                else:
                    print(f"{m.question[:50]:<50} {yes_ask:>8.4f} {no_ask:>8.4f} {total:>7.4f} {spread:>+7.4f} {arb:>5} yd={y_depth}/{n_depth} (no VWAP depth)")
            else:
                print(f"{m.question[:50]:<50}  (one-sided or empty book)")

    print("-" * 90)
    print(f"Checked {checked} markets, found {arb_count} arbitrage opportunities")
    print(f"Note: P_yes + P_no typically >= 1.998 on Polymarket's efficient markets.")
    print(f"      Real arb opportunities are rare and fleeting (sub-second).")

asyncio.run(main())
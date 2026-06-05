#!/usr/bin/env python3
"""Check market tick size and min order size."""
import os, sys, asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")
proxy_rc = Path.home() / ".proxyrc"
if proxy_rc.exists():
    for line in proxy_rc.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" in line and not line.startswith("#"):
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())
import httpx
try:
    import py_clob_client_v2.http_helpers.helpers as _v2h
    proxy_url = os.environ.get("https_proxy") or os.environ.get("http_proxy")
    if proxy_url:
        _v2h._http_client = httpx.Client(proxy=proxy_url, timeout=httpx.Timeout(30.0), follow_redirects=True)
except Exception:
    pass
from core.clob_client import get_clob_client

client = get_clob_client()
token_id = "44943849810372323794029980223633025505608475113464884883166633823014162392768"

async def main():
    try:
        ts = await asyncio.to_thread(client.get_tick_size, token_id)
        print(f"tick_size: {ts}")
    except Exception as e:
        print(f"tick_size error: {e}")
    try:
        ms = await asyncio.to_thread(client.get_min_order_size, token_id)
        print(f"min_order_size: {ms}")
    except Exception as e:
        print(f"min_order_size error: {e}")
    # Try a GTC test order at best_bid
    from py_clob_client_v2.clob_types import OrderArgs, OrderType as ClobOrderType
    order_args = OrderArgs(token_id=token_id, price=0.55, size=5.0, side="BUY")
    try:
        signed = await asyncio.to_thread(client.create_order, order_args)
        resp = await asyncio.to_thread(client.post_order, signed, ClobOrderType.GTC, True)  # post_only
        print(f"post_only order resp: {resp}")
        if isinstance(resp, dict) and resp.get("orderID"):
            oid = resp["orderID"]
            print(f"Order placed! ID={oid[:20]}")
            await asyncio.sleep(1)
            # Cancel it
            cancel_resp = await asyncio.to_thread(client.cancel, oid)
            print(f"Cancel resp: {cancel_resp}")
    except Exception as e:
        print(f"Order error: {type(e).__name__}: {str(e)[:300]}")

asyncio.run(main())
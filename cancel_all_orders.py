#!/usr/bin/env python3
"""Cancel all live Maker orders - emergency stop"""
import os, sys, asyncio, json
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

async def main():
    # Get open orders
    try:
        orders_resp = await asyncio.to_thread(client.get_open_orders)
    except Exception as e:
        print(f"get_open_orders error: {e}")
        return

    if isinstance(orders_resp, list):
        live_orders = orders_resp
    elif isinstance(orders_resp, dict):
        live_orders = orders_resp.get("orders", orders_resp.get("data", []))
    else:
        print(f"Unexpected response type: {type(orders_resp)}")
        print(str(orders_resp)[:500])
        return

    print(f"Found {len(live_orders)} live orders")

    # Cancel all
    from py_clob_client_v2.clob_types import OrderPayload
    cancelled = 0
    for order in live_orders:
        oid = order.get("id", order.get("orderID", "")) if isinstance(order, dict) else str(order)
        print(f"  Cancelling {oid[:20]}...")
        try:
            payload = OrderPayload(orderID=oid)
            resp = await asyncio.to_thread(client.cancel_order, payload)
            cancelled += 1
            print(f"    OK: {resp}")
        except Exception as e:
            print(f"    Error: {e}")

    print(f"\nCancelled {cancelled}/{len(live_orders)} orders")

asyncio.run(main())
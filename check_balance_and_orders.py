#!/usr/bin/env python3
"""Check balance and open orders"""
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

async def main():
    c = get_clob_client()

    # Check balance - use get_collateral_balance
    try:
        import asyncio
        bal = await asyncio.to_thread(c.get_collateral_balance)
        print(f"Balance: {bal}")
    except Exception as e:
        print(f"Balance error: {e}")

    # Check open orders
    try:
        orders = await asyncio.to_thread(c.get_open_orders)
        if isinstance(orders, list):
            print(f"Open orders: {len(orders)}")
            for o in orders[:5]:
                if isinstance(o, dict):
                    print(f"  {o.get('id','?')[:20]} price={o.get('price')} size={o.get('original_size')} side={o.get('side')} status={o.get('status')}")
        else:
            print(f"Open orders response: {str(orders)[:300]}")
    except Exception as e:
        print(f"Open orders error: {e}")

asyncio.run(main())
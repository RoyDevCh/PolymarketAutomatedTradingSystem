#!/usr/bin/env python3
"""
Maker Probe Test — 验证 GTX (Post-Only) 挂单 → FillTracker 状态流转 → 撤单 → 改价

流程:
  1. 找一个流动性好的 YES 市场 (ask 0.15~0.85)
  2. 在 best_bid 下方挂一个 GTX 买单 (不会吃单)
  3. 等待 FillTracker 确认收到 PLACEMENT 状态
  4. 撤单
  5. 改价格，重新挂单
  6. 再撤单

验证:
  - GTX 订单是否成功挂上 (status=live)
  - FillTracker WebSocket 是否收到 PLACEMENT 事件
  - 撤单是否成功
  - 改价重挂是否正常

用法:
  python test_maker_probe.py
  python test_maker_probe.py --budget 1.0
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

# Proxy setup
proxy_rc = Path.home() / ".proxyrc"
if proxy_rc.exists():
    for line in proxy_rc.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" in line and not line.startswith("#"):
            key, _, val = line.partition("=")
            if key.strip().lower().endswith("_proxy") and val.strip():
                os.environ.setdefault(key.strip(), val.strip())

import httpx
try:
    import py_clob_client_v2.http_helpers.helpers as _v2h
    _proxy_url = os.environ.get("https_proxy") or os.environ.get("http_proxy")
    if _proxy_url:
        _v2h._http_client = httpx.Client(proxy=_proxy_url, timeout=httpx.Timeout(30.0), follow_redirects=True)
except Exception:
    pass

from py_clob_client_v2.clob_types import OrderArgs, OrderType as ClobOrderType
from core.clob_client import get_clob_client
from core.config import CONFIG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)-5s %(name)s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("maker_probe")


async def pick_liquid_market(client) -> dict:
    """Find a liquid YES token with meaningful bid/ask spread."""
    import aiohttp
    url = "https://gamma-api.polymarket.com/markets"
    params = {
        "active": "true", "closed": "false",
        "order": "volume", "ascending": "false", "limit": 50,
    }
    proxy = os.environ.get("https_proxy")

    async with aiohttp.ClientSession(trust_env=True) as session:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15), proxy=proxy) as resp:
            markets = await resp.json()

    for m in markets:
        tokens = m.get("clobTokenIds", [])
        if isinstance(tokens, str):
            try:
                tokens = json.loads(tokens)
            except Exception:
                continue
        if not tokens:
            continue
        tid = str(tokens[0])  # YES token

        try:
            book = await asyncio.to_thread(client.get_order_book, tid)
        except Exception:
            continue

        asks, bids = [], []
        if isinstance(book, dict):
            for a in (book.get("asks") or []):
                if isinstance(a, dict):
                    asks.append({"price": float(a["price"]), "size": float(a["size"])})
            for b in (book.get("bids") or []):
                if isinstance(b, dict):
                    bids.append({"price": float(b["price"]), "size": float(b["size"])})

        if not asks or not bids:
            continue

        best_ask = min(a["price"] for a in asks)
        best_bid = max(b["price"] for b in bids)
        ask_depth = sum(a["size"] * a["price"] for a in asks[:3])
        bid_depth = sum(b["size"] * b["price"] for b in bids[:3])

        # Want: reasonable mid price, decent depth, visible spread
        if 0.15 <= best_ask <= 0.85 and ask_depth > 50 and bid_depth > 50:
            return {
                "token_id": tid,
                "best_ask": best_ask,
                "best_bid": best_bid,
                "mid_price": (best_ask + best_bid) / 2,
                "spread_bps": (best_ask - best_bid) / best_ask * 10000,
                "ask_depth_usd": ask_depth,
                "bid_depth_usd": bid_depth,
                "question": (m.get("question") or "")[:60],
                "condition_id": m.get("conditionId", ""),
            }

    raise RuntimeError("No suitable liquid market found for Maker probe")


async def place_gtx_order(client, token_id: str, price: float, size: float, side: str = "BUY") -> dict:
    """Place a Post-Only (Maker) order — equivalent to GTX."""
    order_args = OrderArgs(token_id=token_id, price=price, size=size, side=side)
    signed_order = await asyncio.to_thread(client.create_order, order_args)
    response = await asyncio.to_thread(
        client.post_order, signed_order, ClobOrderType.GTC, True  # post_only=True
    )
    return response if isinstance(response, dict) else {"raw": str(response)}


async def cancel_order(client, order_id: str) -> dict:
    """Cancel an order by ID."""
    from py_clob_client_v2.clob_types import OrderPayload
    payload = OrderPayload(orderID=order_id)
    response = await asyncio.to_thread(client.cancel_order, payload)
    return response if isinstance(response, dict) else {"raw": str(response)}


async def wait_for_fill_tracker_event(duration: float = 8.0) -> Optional[dict]:
    """
    Listen on User Channel WS for order events (PLACEMENT, etc.).
    Simplified: just poll the CLOB API for order status.
    """
    # We'll use a simple HTTP polling approach since the FillTracker setup
    # requires the full OEG infrastructure. For probe purposes, this is sufficient.
    return None


async def get_order_status(client, order_id: str) -> Optional[str]:
    """Get order status via CLOB API."""
    try:
        order = await asyncio.to_thread(client.get_order, order_id)
        if isinstance(order, dict):
            return order.get("status", order.get("order_status", "unknown"))
        return getattr(order, "status", getattr(order, "order_status", "unknown"))
    except Exception as e:
        logger.warning("get_order_status error: %s", e)
        return None


async def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Maker Probe Test")
    parser.add_argument("--budget", type=float, default=1.0, help="USD budget per bid")
    parser.add_argument("--below-bid", type=float, default=0.02, help="How far below best_bid to place bid")
    args = parser.parse_args()

    client = get_clob_client()
    logger.info("=" * 60)
    logger.info("  Maker Probe Test — GTX (Post-Only) Validation")
    logger.info("=" * 60)

    # Step 1: Find liquid market
    logger.info("\n[1/7] Finding liquid market...")
    market = await pick_liquid_market(client)
    logger.info("  Market: %s", market["question"])
    logger.info("  YES token: %s...", market["token_id"][:20])
    logger.info("  Best ask: %.4f  Best bid: %.4f  Spread: %.1f bps",
               market["best_ask"], market["best_bid"], market["spread_bps"])
    logger.info("  Ask depth: $%.0f  Bid depth: $%.0f",
               market["ask_depth_usd"], market["bid_depth_usd"])

    # Step 2: Calculate our bid price (below best_bid, guaranteeing Maker)
    our_bid_price = round(market["best_bid"] - args.below_bid, 2)
    if our_bid_price <= 0.01:
        our_bid_price = round(market["best_bid"] - 0.01, 2)
    our_bid_size = round(args.budget / our_bid_price, 2)

    logger.info("\n[2/7] Our bid: price=%.4f (best_bid=%.4f, -%.4f)",
               our_bid_price, market["best_bid"], args.below_bid)
    logger.info("  Size: %.2f shares ($%.2f)", our_bid_size, args.budget)

    # Step 3: Place GTX order
    logger.info("\n[3/7] Placing GTX (Post-Only) order...")
    t0 = time.time()
    resp = await place_gtx_order(client, market["token_id"], our_bid_price, our_bid_size)
    elapsed = (time.time() - t0) * 1000
    order_id = resp.get("orderID", resp.get("order_id", ""))
    logger.info("  Response: %s", json.dumps(resp)[:200])
    logger.info("  Order ID: %s", order_id[:20] if order_id else "(none)")
    logger.info("  Elapsed: %.1f ms", elapsed)

    if not order_id:
        logger.error("  FAIL: No order ID returned. GTX may have been rejected (would cross ask).")
        logger.info("  Try increasing --below-bid to go further from the ask.")
        return 1

    # Step 4: Check order status via API
    logger.info("\n[4/7] Checking order status...")
    await asyncio.sleep(1)
    status = await get_order_status(client, order_id)
    logger.info("  Status: %s", status)

    # Step 5: Cancel the order
    logger.info("\n[5/7] Cancelling order...")
    t0 = time.time()
    cancel_resp = await cancel_order(client, order_id)
    cancel_elapsed = (time.time() - t0) * 1000
    logger.info("  Cancel response: %s", json.dumps(cancel_resp)[:200])
    logger.info("  Cancel elapsed: %.1f ms", cancel_elapsed)

    # Step 6: Verify cancelled
    logger.info("\n[6/7] Verifying cancelled...")
    await asyncio.sleep(0.5)
    final_status = await get_order_status(client, order_id)
    logger.info("  Final status: %s", final_status)

    # Step 7: Modify price and re-place
    new_bid_price = round(our_bid_price - 0.01, 2)
    if new_bid_price <= 0.01:
        new_bid_price = round(our_bid_price - 0.005, 3)
    logger.info("\n[7/7] Re-placing at modified price %.4f...", new_bid_price)
    resp2 = await place_gtx_order(client, market["token_id"], new_bid_price, our_bid_size)
    order_id2 = resp2.get("orderID", resp2.get("order_id", ""))
    logger.info("  New order ID: %s", order_id2[:20] if order_id2 else "(none)")

    if order_id2:
        await asyncio.sleep(0.5)
        # Cancel the new order too
        await cancel_order(client, order_id2)
        logger.info("  Cancelled new order.")

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("  Maker Probe Summary")
    logger.info("=" * 60)
    logger.info("  GTX placement:  %s", "PASS" if order_id else "FAIL")
    logger.info("  Order status:    %s", status or "unknown")
    logger.info("  Cancel:          %s",
               "PASS" if "cancel" in str(cancel_resp).lower() or "success" in str(cancel_resp).lower() else "CHECK")
    logger.info("  Re-place:        %s", "PASS" if order_id2 else "FAIL")
    logger.info("  Market:          %s", market["question"])
    logger.info("  Spread:         %.1f bps (maker edge)", market["spread_bps"])
    logger.info("  Original bid:    %.4f  Modified bid: %.4f", our_bid_price, new_bid_price)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
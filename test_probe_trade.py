#!/usr/bin/env python3
"""~$0.50 taker probe: FOK at best ask + trade_log fill update."""
import asyncio
import json
import logging
import time
import uuid
import urllib.request

from dotenv import load_dotenv
from py_clob_client_v2.clob_types import OrderArgs, OrderType as ClobOrderType

from core.clob_client import get_clob_client
from core.rmc import RiskManagementCenter

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger("probe")
TARGET_USDC = 0.5


def _px(level):
    if isinstance(level, dict):
        return float(level.get("price", 1e9))
    return float(getattr(level, "price", level))


def _sz(level):
    if isinstance(level, dict):
        return float(level.get("size", 0) or 0)
    return float(getattr(level, "size", 0) or 0)


async def pick_market(client):
    url = (
        "https://gamma-api.polymarket.com/markets?"
        "active=true&closed=false&limit=40&order=volumeNum&ascending=false"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "probe/1"})

    def _fetch():
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())

    markets = await asyncio.to_thread(_fetch)
    for m in markets:
        raw = m.get("clobTokenIds") or []
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not raw:
            continue
        tid = str(raw[0])
        book = await asyncio.to_thread(client.get_order_book, tid)
        raw_asks = book.get("asks") if isinstance(book, dict) else getattr(book, "asks", None)
        if not raw_asks:
            continue
        if isinstance(raw_asks, list):
            asks = raw_asks
        elif isinstance(raw_asks, dict):
            asks = [raw_asks] if "price" in raw_asks else [
                {"price": k, "size": v} for k, v in raw_asks.items()
            ]
        elif hasattr(raw_asks, "price"):
            asks = [raw_asks]
        else:
            continue
        best = min(asks, key=_px)
        ask, depth = _px(best), _sz(best)
        if 0.15 <= ask <= 0.85 and depth * ask >= TARGET_USDC * 0.9:
            cond = m.get("conditionId") or m.get("condition_id") or "probe"
            return tid, ask, cond, (m.get("question") or "probe")[:80]
    raise RuntimeError("no liquid market for probe")


async def main():
    client = get_clob_client()
    token_id, ask, cond, question = await pick_market(client)
    size = round(TARGET_USDC / ask, 2)
    signal_id = str(uuid.uuid4())
    LOGGER.info("probe token=%s ask=%.4f size=%.2f", token_id[:12], ask, size)

    rmc = RiskManagementCenter()
    await rmc.init_db()
    await rmc._db.execute(
        "INSERT INTO trade_log (timestamp, signal_id, condition_id, market_question, "
        "yes_token_id, no_token_id, yes_price, no_price, yes_size, no_size, "
        "expected_profit, yes_status, no_status) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            time.time(), signal_id, cond, question,
            token_id, token_id, ask, 1.0 - ask, size, size, 0.0, "PENDING", "PENDING",
        ),
    )
    await rmc._db.commit()

    order_args = OrderArgs(token_id=token_id, price=ask, size=size, side="BUY")
    signed = await asyncio.to_thread(client.create_order, order_args)
    resp = await asyncio.to_thread(client.post_order, signed, ClobOrderType.FOK)
    LOGGER.info("order_resp=%s", resp)

    fill_price = ask
    fill_size = size
    if isinstance(resp, dict):
        fill_price = float(resp.get("avg_price") or resp.get("price") or ask)
        fill_size = float(resp.get("filled_size") or resp.get("size") or size)

    await rmc.on_fill_update(signal_id, "YES", fill_price, fill_size, "CONFIRMED")
    cur = await rmc._db.execute(
        "SELECT yes_fill_price, yes_filled_size, yes_status FROM trade_log WHERE signal_id=?",
        (signal_id,),
    )
    row = await cur.fetchone()
    LOGGER.info("trade_log_row=%s", row)
    await rmc.close_db()
    if not row or row[0] is None:
        raise RuntimeError("trade_log fill not updated")


if __name__ == "__main__":
    asyncio.run(main())

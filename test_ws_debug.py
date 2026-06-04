import asyncio, aiohttp, json, os
os.environ["https_proxy"] = "http://127.0.0.1:7890"
os.environ["http_proxy"] = "http://127.0.0.1:7890"

async def test():
    proxy = "http://127.0.0.1:7890"
    conn = aiohttp.TCPConnector()
    token_id = "0"

    async with aiohttp.ClientSession(connector=conn, trust_env=True) as s:
        url = "https://gamma-api.polymarket.com/markets?active=true&closed=false&order=volume&ascending=false&limit=1"
        async with s.get(url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=15)) as r:
            data = await r.json()
            if data:
                clob_ids = data[0].get("clobTokenIds", [])
                if isinstance(clob_ids, str):
                    clob_ids = json.loads(clob_ids)
                token_id = clob_ids[0] if clob_ids else "0"
                print("Using token: " + token_id[:40] + "...")

    session = aiohttp.ClientSession(trust_env=True)
    ws_url = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    ws = await session.ws_connect(ws_url, proxy=proxy, heartbeat=30)

    subscribe_msg = {"assets_ids": [token_id], "type": "market", "custom_feature_enabled": True}
    await ws.send_json(subscribe_msg)
    print("Subscribed! Waiting for messages (20s)...")

    msg_count = 0
    try:
        while msg_count < 8:
            msg = await asyncio.wait_for(ws.receive(), timeout=20)
            if msg.type == aiohttp.WSMsgType.TEXT:
                if msg.data == "PONG":
                    print("  [PONG]")
                    continue
                raw = msg.data
                # WS can send a JSON array or a single object
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    print("  [non-JSON]: " + raw[:80])
                    continue

                # Normalize to list
                events = parsed if isinstance(parsed, list) else [parsed]

                for data in events:
                    etype = data.get("event_type", data.get("type", "unknown"))
                    msg_count += 1
                    print("\nMsg #" + str(msg_count) + ": event_type=" + str(etype))

                    if etype == "book":
                        print("  asset_id: " + str(data.get("asset_id", ""))[:40])
                        asks = data.get("asks", [])
                        bids = data.get("bids", [])
                        if isinstance(asks, list) and asks:
                            print("  asks[0]: " + str(asks[0])[:100])
                        if isinstance(bids, list) and bids:
                            print("  bids[0]: " + str(bids[0])[:100])
                        print("  hash: " + str(data.get("hash", ""))[:20])

                    elif etype == "price_change":
                        changes = data.get("price_changes", [])
                        if isinstance(changes, list) and changes:
                            c = changes[0]
                            print("  change: " + str(c)[:150])

                    elif etype == "last_trade_price":
                        print("  price: " + str(data.get("price", "")) + " side: " + str(data.get("side", "")))

                    else:
                        keys = list(data.keys())[:6]
                        print("  keys: " + str(keys))

            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                print("WebSocket closed")
                break

    except asyncio.TimeoutError:
        print("Timeout (no more messages)")

    await ws.close()
    await session.close()
    print("\nDone, received " + str(msg_count) + " events")

asyncio.run(test())
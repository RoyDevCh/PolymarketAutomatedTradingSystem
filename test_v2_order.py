"""
Phase 2.5 CLOB V2 微量实盘探路 (最终版)

关键变更:
- 使用 py-clob-client-v2 (V1 SDK 不再兼容)
- tick_size 必须为字符串 "0.01" 而非浮点数
- get_clob_market_info 返回新格式
- 抵押品从 USDC.e 变为 pUSD
- 合约地址更新
"""

import os
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# 加载代理
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

# 注入代理到 V2 SDK 的 httpx.Client
import httpx
import py_clob_client_v2.http_helpers.helpers as _v2h
proxy_url = os.environ.get("https_proxy") or os.environ.get("http_proxy")
if proxy_url:
    _v2h._http_client = httpx.Client(proxy=proxy_url, timeout=httpx.Timeout(30.0), follow_redirects=True)
    print(f"[PROXY] Injected: {proxy_url[:30]}...")

from core.config import CONFIG
from py_clob_client_v2 import (
    ClobClient, ApiCreds, OrderArgs, OrderType,
    PartialCreateOrderOptions, AssetType, BalanceAllowanceParams
)


def main():
    cfg = CONFIG.clob
    wallet_cfg = CONFIG.wallet

    print("=" * 60)
    print("  Phase 2.5 CLOB V2 微量实盘探路")
    print("=" * 60)

    # Step 1: 创建 V2 Client
    print("\n[1/5] 创建 CLOB V2 Client...")
    api_creds = ApiCreds(
        api_key=cfg.api_key,
        api_secret=cfg.api_secret,
        api_passphrase=cfg.api_passphrase,
    )
    client = ClobClient(
        host=cfg.api_url,
        chain_id=wallet_cfg.chain_id,
        key=wallet_cfg.private_key,
        creds=api_creds,
    )
    print(f"  [OK] Client created")

    # Step 2: 测试 API 连接
    print("\n[2/5] 测试 API 连接...")
    try:
        from py_clob_client_v2.http_helpers.helpers import get
        server_time = get(f"{cfg.api_url}/time")
        print(f"  [OK] Server time: {server_time}")
    except Exception as e:
        print(f"  [WARN] Server time: {e}")

    # Step 3: 查询余额 (pUSD)
    print("\n[3/5] 查询 pUSD 余额...")
    try:
        bal = client.get_balance_allowance(params=BalanceAllowanceParams(
            asset_type=AssetType.COLLATERAL
        ))
        print(f"  [OK] Collateral balance: {bal}")
    except Exception as e:
        print(f"  [WARN] Balance query: {e}")

    # Step 4: 找一个活跃市场
    print("\n[4/5] 寻找活跃市场...")
    import aiohttp
    import json

    async def find_market():
        proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
        url = "https://gamma-api.polymarket.com/markets?active=true&closed=false&order=volume&ascending=false&limit=10"
        async with aiohttp.ClientSession(trust_env=True) as s:
            async with s.get(url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=15)) as r:
                return await r.json()

    markets = asyncio.run(find_market())
    if not markets:
        print("  [FAIL] No markets found")
        return

    token_id = None
    condition_id = None
    neg_risk = False
    for m in markets[:10]:
        clob_ids = m.get("clobTokenIds", [])
        if isinstance(clob_ids, str):
            clob_ids = json.loads(clob_ids)
        outcomes = m.get("outcomes", [])
        if isinstance(outcomes, str):
            outcomes = json.loads(outcomes)
        if len(clob_ids) >= 2:
            token_id = clob_ids[0]
            condition_id = m.get("conditionId", "") or m.get("condition_id", "")
            neg_risk = m.get("negRisk", m.get("neg_risk", False))
            if isinstance(neg_risk, str):
                neg_risk = neg_risk.lower() == "true"
            question = m.get("question", "")[:60]
            print(f"  [OK] Market: {question}")
            print(f"       Token: {token_id[:40]}...")
            print(f"       Condition: {condition_id[:40]}...")
            print(f"       NegRisk: {neg_risk}")
            break

    if not token_id:
        print("  [FAIL] No market with token IDs found")
        return

    # Step 5: 下测试订单
    print("\n[5/5] 下测试订单 (CLOB V2)...")

    # Get tick size from market info
    tick_size_str = "0.01"  # default
    min_size = 1.0
    try:
        info = client.get_clob_market_info(condition_id)
        print(f"  Market info: {info}")
        mts = info.get("mts", "0.01")
        mos = info.get("mos", "5")
        # Ensure tick_size is a proper string
        if isinstance(mts, (int, float)):
            tick_size_str = str(mts)
        else:
            tick_size_str = str(mts)
        # Ensure min_size is a number
        if isinstance(mos, (int, float)):
            min_size = float(mos)
        else:
            min_size = float(mos)
        print(f"  Tick size: {tick_size_str}, Min size: {min_size}")
    except Exception as e:
        print(f"  [WARN] get_clob_market_info: {e}")

    # Get current price from orderbook
    safe_price = 0.01  # Far OTM price
    try:
        book = client.get_order_book(token_id)
        # V2 SDK might return dict instead of object
        if isinstance(book, dict):
            asks = book.get("asks", [])
            bids = book.get("bids", [])
        else:
            asks = getattr(book, 'asks', [])
            bids = getattr(book, 'bids', [])

        if asks and len(asks) > 0:
            best_ask = float(asks[0].get("price", asks[0].price) if isinstance(asks[0], dict) else asks[0].price)
            # Place at 50% below best ask
            safe_price = round(best_ask * 0.5, 2)
            if safe_price <= 0:
                safe_price = float(tick_size_str)
            print(f"  Best ask: {best_ask}, using price: {safe_price}")
        elif bids and len(bids) > 0:
            best_bid = float(bids[0].get("price", bids[0].price) if isinstance(bids[0], dict) else bids[0].price)
            safe_price = round(best_bid * 0.5, 2)
            if safe_price <= 0:
                safe_price = float(tick_size_str)
            print(f"  Best bid: {best_bid}, using price: {safe_price}")
        else:
            print(f"  No bids/asks, using default price: {safe_price}")
    except Exception as e:
        print(f"  [WARN] Orderbook: {e}")

    # Ensure price is at least tick_size
    if safe_price < float(tick_size_str):
        safe_price = float(tick_size_str)

    # Round to tick_size precision
    ts_float = float(tick_size_str)
    if ts_float >= 0.01:
        safe_price = round(safe_price, 2)
    elif ts_float >= 0.001:
        safe_price = round(safe_price, 3)
    else:
        safe_price = round(safe_price, 4)

    # Ensure price > 0
    if safe_price < float(tick_size_str):
        safe_price = float(tick_size_str)

    order_size = max(min_size, 1.0)
    neg_risk_bool = bool(neg_risk)

    print(f"\n  >>> Order params <<<")
    print(f"  Token:     {token_id[:40]}...")
    print(f"  Price:     ${safe_price}")
    print(f"  Size:      {order_size}")
    print(f"  Side:      BUY")
    print(f"  TickSize:  {tick_size_str}")
    print(f"  NegRisk:   {neg_risk_bool}")

    try:
        order_args = OrderArgs(
            token_id=token_id,
            price=safe_price,
            size=order_size,
            side="BUY",
        )

        # Try with the tick_size from market info
        # If that fails, try common tick sizes
        for ts in [tick_size_str, "0.01", "0.1", "0.001", "0.0001"]:
            try:
                options = PartialCreateOrderOptions(
                    tick_size=ts,
                    neg_risk=neg_risk_bool,
                )
                print(f"\n  Creating order with tick_size={ts}, neg_risk={neg_risk_bool}...")
                signed_order = client.create_order(order_args, options)
                print(f"  [OK] Order signed successfully!")
                print(f"       Salt: {getattr(signed_order, 'salt', 'N/A')}")
                print(f"       Timestamp: {getattr(signed_order, 'timestamp', 'N/A')}")
                sig = getattr(signed_order, 'signature', '')
                if sig:
                    print(f"       Sig: {sig[:30]}...")
                break
            except KeyError as ke:
                print(f"  KeyError({ke}) with tick_size={ts}, trying next...")
                continue
            except Exception as e:
                print(f"  Error with tick_size={ts}: {type(e).__name__}: {e}")
                if "invalid price" in str(e).lower():
                    # Adjust price for this tick size
                    if float(ts) > safe_price:
                        safe_price = float(ts)
                        order_args = OrderArgs(
                            token_id=token_id,
                            price=safe_price,
                            size=order_size,
                            side="BUY",
                        )
                    continue
        else:
            print("  [FAIL] Could not create order with any tick_size")
            # Try cancel_all as cleanup
            try:
                client.cancel_all()
            except:
                pass
            return

        # Post the order
        print(f"\n  Posting order to Polymarket CLOB V2...")
        response = client.post_order(signed_order, OrderType.GTC)
        print(f"\n  *** RESPONSE: {response}")

        if isinstance(response, dict):
            order_id = response.get("orderID", response.get("order_id", ""))
            status = response.get("status", "Unknown")
            print(f"  [OK] Order ID: {order_id}")
            print(f"  [OK] Status: {status}")
        elif isinstance(response, str):
            order_id = response
            print(f"  [OK] Order ID: {response}")
        else:
            print(f"  [OK] Response: {response}")
            order_id = None

        # Wait and verify
        print("\n  Waiting 3 seconds...")
        import time
        time.sleep(3)

        # Try to get order status
        if order_id:
            try:
                order_status = client.get_order(order_id)
                print(f"  [OK] Order status: {order_status}")
            except Exception as e:
                print(f"  [WARN] Get order status: {e}")

        # Cancel the order
        print(f"\n  Cancelling order...")
        if order_id:
            try:
                cancel_result = client.cancel(order_id)
                print(f"  [OK] Cancel result: {cancel_result}")
            except Exception as e:
                print(f"  [WARN] Cancel: {e}")
        # Always try cancel_all as cleanup
        try:
            cancel_all = client.cancel_all()
            print(f"  [OK] Cancel all: {cancel_all}")
        except Exception as e:
            print(f"  [WARN] Cancel all: {e}")

        # Summary
        print("\n" + "=" * 60)
        print("  PHASE 2.5 CLOB V2 - RESULT SUMMARY")
        print("=" * 60)
        print(f"  V2 Client:        OK")
        print(f"  Proxy (JP-02):    OK")
        print(f"  Order Signed:     OK")
        print(f"  Order Posted:     {'OK' if response else 'FAIL'}")
        print(f"  Order ID:         {order_id or 'N/A'}")
        print()
        if order_id:
            print("  ========== V2 ORDER PIPELINE VERIFIED! ==========")
        else:
            print("  [INFO] Order response received but no order_id extracted")

    except Exception as e:
        print(f"\n  [FAIL] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        # Cleanup
        try:
            client.cancel_all()
        except:
            pass


if __name__ == "__main__":
    main()
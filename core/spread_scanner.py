"""
Spread Scanner — 扫描所有监控市场的真实价差分布。

诊断 SPE 0 信号问题:
  1. 显示每个市场的 P_yes + P_no (best ask) 以及 VWAP 价差
  2. 统计价差直方图 (看是"极度有效"还是"阈值卡死")
  3. 找出最接近套利的前 N 个市场

用法:
  python -m core.spread_scanner
  python -m core.spread_scanner --top 20 --budget 2.0
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

# 加载 .env
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import aiohttp
import structlog

from core.config import CONFIG
from core.clob_client import get_clob_client
from core.models import MarketInfo, OrderBookSnapshot, PriceLevel

logger = structlog.get_logger(__name__)

# 代理
_PROXY = os.environ.get("https_proxy") or os.environ.get("http_proxy") or None


async def fetch_markets(session: aiohttp.ClientSession) -> list[dict]:
    """从 Gamma API 拉取市场列表"""
    url = f"{CONFIG.gamma.api_url}/markets"
    params = {
        "active": "true",
        "closed": "false",
        "order": "volume",
        "ascending": "false",
        "limit": 200,
    }
    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15), proxy=_PROXY) as resp:
        if resp.status != 200:
            print(f"Gamma API error: {resp.status}")
            return []
        return await resp.json()


def parse_market(item: dict) -> Optional[MarketInfo]:
    """解析单个市场数据"""
    condition_id = item.get("conditionId", "") or item.get("condition_id", "")
    if not condition_id:
        return None

    clob_token_ids = item.get("clobTokenIds", [])
    if isinstance(clob_token_ids, str):
        try:
            clob_token_ids = json.loads(clob_token_ids)
        except (json.JSONDecodeError, TypeError):
            clob_token_ids = []

    outcomes = item.get("outcomes", [])
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except (json.JSONDecodeError, TypeError):
            outcomes = []

    yes_token = no_token = ""
    if isinstance(clob_token_ids, list) and len(clob_token_ids) >= 2:
        if len(outcomes) >= 2:
            for i, tid in enumerate(clob_token_ids):
                o = str(outcomes[i]).upper() if i < len(outcomes) else ""
                if o == "YES":
                    yes_token = tid
                elif o == "NO":
                    no_token = tid
        if not yes_token:
            yes_token = clob_token_ids[0]
            no_token = clob_token_ids[1]

    if not yes_token or not no_token:
        tokens = item.get("tokens", [])
        if isinstance(tokens, list):
            for tok in tokens:
                o = str(tok.get("outcome", "")).upper()
                if o == "YES":
                    yes_token = tok.get("token_id", "")
                elif o == "NO":
                    no_token = tok.get("token_id", "")

    if not yes_token or not no_token:
        return None

    volume = float(item.get("volumeNum", 0) or item.get("volume", 0) or 0)
    liquidity = float(item.get("liquidityNum", 0) or item.get("liquidity", 0) or 0)

    if volume < CONFIG.gamma.min_volume:
        return None

    return MarketInfo(
        condition_id=condition_id,
        question=item.get("question", "")[:80],
        yes_token_id=yes_token,
        no_token_id=no_token,
        volume=volume,
        liquidity=liquidity,
    )


def calculate_vwap(asks: list, budget_usd: float) -> tuple[float, float]:
    """返回 (vwap, acquireable_size)"""
    if not asks:
        return 0.0, 0.0
    remaining = budget_usd
    total_cost = total_size = 0.0
    for level in asks:
        if remaining <= 0:
            break
        price = float(level.price) if hasattr(level, "price") else float(level.get("price", 0))
        size = float(level.size) if hasattr(level, "size") else float(level.get("size", 0))
        level_cost = price * size
        if level_cost <= remaining:
            total_cost += level_cost
            total_size += size
            remaining -= level_cost
        else:
            partial = remaining / price
            total_cost += remaining
            total_size += partial
            remaining = 0
    if total_size <= 0:
        return 0.0, 0.0
    return total_cost / total_size, total_size


async def fetch_order_book(client, token_id: str) -> Optional[dict]:
    """获取某个 token 的订单簿"""
    try:
        book = await asyncio.to_thread(client.get_order_book, token_id)
        return book
    except Exception as e:
        logger.debug("order_book_fetch_error", token_id=token_id[:16], error=str(e)[:100])
        return None


def extract_asks_bids(book) -> tuple[list, list]:
    """从 ClobClient 返回的订单簿提取 asks/bids 列表
    
    CLOB V2 get_order_book 可能返回:
      - dict: {"asks": [{"price":..., "size":...}], "bids": [...]}
      - object: .asks / .bids attributes
    """
    if book is None:
        return [], []

    # Handle dict response (V2 SDK returns dict)
    if isinstance(book, dict):
        asks_raw = book.get("asks", []) or []
        bids_raw = book.get("bids", []) or []
    else:
        asks_raw = getattr(book, "asks", []) or []
        bids_raw = getattr(book, "bids", []) or []

    asks = []
    for a in asks_raw:
        if isinstance(a, dict):
            price = float(a.get("price", 0))
            size = float(a.get("size", 0))
        else:
            price = float(a.price) if hasattr(a, "price") else 0
            size = float(a.size) if hasattr(a, "size") else 0
        if price > 0 and size > 0:
            asks.append({"price": price, "size": size})
    bids = []
    for b in bids_raw:
        if isinstance(b, dict):
            price = float(b.get("price", 0))
            size = float(b.get("size", 0))
        else:
            price = float(b.price) if hasattr(b, "price") else 0
            size = float(b.size) if hasattr(b, "size") else 0
        if price > 0 and size > 0:
            bids.append({"price": price, "size": size})
    asks.sort(key=lambda x: x["price"])
    bids.sort(key=lambda x: -x["price"])
    return asks, bids


async def scan_spreads(top_n: int = 20, budget_usd: float = 2.0) -> None:
    """扫描所有市场的价差分布"""
    print("=" * 70)
    print("  Spread Scanner — 诊断 SPE 0 信号问题")
    print(f"  预算: ${budget_usd} | 显示前 {top_n} 个最接近套利的市场")
    print("=" * 70)

    # 拉取市场
    async with aiohttp.ClientSession(trust_env=True) as session:
        raw = await fetch_markets(session)

    markets = []
    for item in raw:
        m = parse_market(item)
        if m:
            markets.append(m)
    print(f"\n发现 {len(markets)} 个活跃市场 (已过滤)\n")

    # 初始化 CLOB Client (proxy injection needed)
    from pathlib import Path as _P
    _proxy_rc = _P.home() / ".proxyrc"
    if _proxy_rc.exists():
        for _line in _proxy_rc.read_text().splitlines():
            _line = _line.strip()
            if _line.startswith("export "):
                _line = _line[len("export "):]
            if "=" in _line and not _line.startswith("#"):
                _key, _, _val = _line.partition("=")
                if _key.strip().lower().endswith("_proxy") and _val.strip():
                    os.environ.setdefault(_key.strip(), _val.strip())

    import httpx
    try:
        import py_clob_client_v2.http_helpers.helpers as _v2h
        _proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
        if _proxy:
            _v2h._http_client = httpx.Client(proxy=_proxy, timeout=httpx.Timeout(30.0), follow_redirects=True)
    except Exception:
        pass

    from core.clob_client import get_clob_client
    try:
        client = get_clob_client()
    except Exception as e:
        print(f"CLOB Client 初始化失败: {e}")
        return

    # 逐一扫描订单簿
    results = []
    errors = 0
    for i, market in enumerate(markets):
        yes_book = await fetch_order_book(client, market.yes_token_id)
        no_book = await fetch_order_book(client, market.no_token_id)

        yes_asks, yes_bids = extract_asks_bids(yes_book)
        no_asks, no_bids = extract_asks_bids(no_book)

        if not yes_asks or not no_asks:
            errors += 1
            continue

        best_ask_yes = yes_asks[0]["price"]
        best_ask_no = no_asks[0]["price"]
        best_bid_yes = yes_bids[0]["price"] if yes_bids else 0
        best_bid_no = no_bids[0]["price"] if no_bids else 0

        # BBO 价差
        bbo_sum = best_ask_yes + best_ask_no
        bbo_spread = 1.0 - bbo_sum

        # VWAP 价差 (模拟实际成交)
        vwap_yes, size_yes = calculate_vwap(yes_asks, budget_usd)
        vwap_no, size_no = calculate_vwap(no_asks, budget_usd)
        vwap_sum = vwap_yes + vwap_no if vwap_yes > 0 and vwap_no > 0 else 2.0
        vwap_spread = 1.0 - vwap_sum
        usable_size = min(size_yes, size_no)

        # 第一档深度
        yes_depth1 = yes_asks[0]["size"]
        no_depth1 = no_asks[0]["size"]

        results.append({
            "question": market.question,
            "condition_id": market.condition_id,
            "best_ask_yes": best_ask_yes,
            "best_ask_no": best_ask_no,
            "bbo_sum": bbo_sum,
            "bbo_spread": bbo_spread,
            "vwap_yes": vwap_yes,
            "vwap_no": vwap_no,
            "vwap_sum": vwap_sum,
            "vwap_spread": vwap_spread,
            "usable_size": usable_size,
            "yes_depth1": yes_depth1,
            "no_depth1": no_depth1,
            "yes_asks_depth": len(yes_asks),
            "no_asks_depth": len(no_asks),
        })

        if (i + 1) % 20 == 0:
            print(f"  已扫描 {i+1}/{len(markets)} ...", end="\r")

    print(f"\n  扫描完成: {len(results)} 个有效市场, {errors} 个获取失败")

    if not results:
        print("无有效数据")
        return

    # 按价差排序 (最大的排最前 = 最接近套利)
    results.sort(key=lambda x: x["bbo_sum"])

    # 价差直方图
    print("\n" + "=" * 70)
    print("  价差直方图 (BBO Sum = Ask_YES + Ask_NO)")
    print("=" * 70)

    buckets = defaultdict(int)
    for r in results:
        s = r["bbo_sum"]
        if s < 0.99:
            buckets["<0.990"] += 1
        elif s < 0.995:
            buckets["0.990-0.995"] += 1
        elif s < 0.998:
            buckets["0.995-0.998"] += 1
        elif s < 0.999:
            buckets["0.998-0.999"] += 1
        elif s < 1.000:
            buckets["0.999-1.000"] += 1
        elif s < 1.001:
            buckets["1.000-1.001"] += 1
        elif s < 1.005:
            buckets["1.001-1.005"] += 1
        else:
            buckets[">=1.005"] += 1

    for label in ["<0.990", "0.990-0.995", "0.995-0.998", "0.998-0.999",
                  "0.999-1.000", "1.000-1.001", "1.001-1.005", ">=1.005"]:
        n = buckets.get(label, 0)
        bar = "█" * n if n else ""
        print(f"  {label:>14s} | {n:4d} {bar}")

    # 当前阈值分析
    threshold = CONFIG.trading.min_profit_threshold
    budget = CONFIG.trading.max_trade_size
    bbo_profitable = sum(1 for r in results if r["bbo_spread"] * budget > threshold)
    vwap_profitable = sum(1 for r in results if r["vwap_spread"] > 0 and r["vwap_spread"] * r["usable_size"] > threshold)

    print(f"\n  当前配置: MIN_PROFIT_THRESHOLD=${threshold}, MAX_TRADE_SIZE=${budget}")
    print(f"  BBO 利润 > ${threshold}: {bbo_profitable} 个市场")
    print(f"  VWAP 利润 > ${threshold}: {vwap_profitable} 个市场")

    # 前 N 个最接近套利的市场
    print("\n" + "=" * 70)
    print(f"  最接近套利的前 {top_n} 个市场")
    print("=" * 70)
    print(f"  {'市场':<40s} {'BBO Sum':>8s} {'BBO Sprd':>9s} {'VWAP Sprd':>10s} {'Depth1 $':>9s}")
    print("  " + "-" * 78)

    for i, r in enumerate(results[:top_n]):
        q = r["question"][:38]
        print(
            f"  {q:<40s} {r['bbo_sum']:>8.4f} {r['bbo_spread']:>+9.4f} "
            f"{r['vwap_spread']:>+10.4f} "
            f"${min(r['yes_depth1'], r['no_depth1']):>7.1f}"
        )

    # 如果没有任何市场有套利空间
    arbitrage_markets = [r for r in results if r["bbo_spread"] > 0]
    if not arbitrage_markets:
        print("\n  ⚠️  当前 0 个市场存在 BBO 套利空间 (Ask_YES + Ask_NO >= 1.0)")
        print("     → 这是 Polymarket 做市商极度有效的正常表现")
        print("     → 套利窗口只会在剧烈消息面爆发时短暂出现")
    else:
        print(f"\n  ✅ 发现 {len(arbitrage_markets)} 个市场存在 BBO 套利空间")

    # 结论
    print("\n" + "=" * 70)
    print("  诊断结论")
    print("=" * 70)
    if bbo_profitable == 0 and vwap_profitable == 0:
        print("  → 可能1确认: 市场极度有效, 静默期无套利窗口")
        print("  → 建议: 运行 poke_spe.py (压力注入) 验证 SPE→OEG 管道")
    elif bbo_profitable > 0 and vwap_profitable == 0:
        print("  → 可能2确认: BBO 有微利, 但 VWAP 穿透后滑点吞噬利润")
        print(f"  → 深度不足: 大多数市场第一档 < ${budget}")
        print("  → 建议: 降低 MAX_TRADE_SIZE 或等待深度改善")
    else:
        print("  → 有套利机会但 MIN_PROFIT_THRESHOLD 可能卡掉了")
        print(f"  → 建议: 降低 MIN_PROFIT_THRESHOLD (当前 ${threshold})")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Polymarket Spread Scanner")
    parser.add_argument("--top", type=int, default=20, help="显示前 N 个市场")
    parser.add_argument("--budget", type=float, default=None, help="模拟预算 (USD)")
    args = parser.parse_args()

    budget = args.budget or CONFIG.trading.max_trade_size
    asyncio.run(scan_spreads(top_n=args.top, budget_usd=budget))


if __name__ == "__main__":
    main()
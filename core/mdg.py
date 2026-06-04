"""
Polymarket 自动套利系统 - 市场数据网关 (MDG)

职责:
1. 通过 Gamma API 定期发现活跃市场
2. 建立 CLOB WebSocket 长连接, 订阅实时订单簿
3. 在本地内存中维护增量订单簿镜像
4. 向下游 SPE 推送 BBO / 完整快照
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Any, Callable, Optional

import aiohttp
import structlog
from sortedcontainers import SortedDict

from core.config import CONFIG
from core.models import MarketInfo, OrderBookSnapshot, PriceLevel

logger = structlog.get_logger(__name__)


class OrderBookMirror:
    """
    本地订单簿镜像
    
    使用 SortedDict 维护价格档位, 实现高效的增量更新:
    - asks: 按价格升序排列 (最低卖价在前)
    - bids: 按价格降序排列 (最高买价在前)
    
    支持两种更新模式:
    1. Delta 增量更新 (WebSocket 推送)
    2. 全量快照替换 (初次订阅或重连)
    """

    def __init__(self, token_id: str, condition_id: str):
        self.token_id = token_id
        self.condition_id = condition_id
        self.asks = SortedDict()   # price -> cumulative_size
        self.bids = SortedDict()   # price -> cumulative_size
        self.last_update_ts: float = 0.0

    def apply_snapshot(self, asks: list[dict], bids: list[dict]) -> None:
        """全量替换订单簿"""
        self.asks.clear()
        self.bids.clear()

        for level in asks:
            price = float(level.get("price", 0))
            size = float(level.get("size", 0))
            if price > 0 and size > 0:
                self.asks[price] = size

        for level in bids:
            price = float(level.get("price", 0))
            size = float(level.get("size", 0))
            if price > 0 and size > 0:
                self.bids[price] = size

        self.last_update_ts = time.time()

    def apply_delta(self, price: float, size: float, side: str) -> None:
        """增量更新单档价位"""
        book = self.asks if side == "sell" else self.bids
        if size == 0:
            # 删除该档位
            book.pop(price, None)
        else:
            book[price] = size
        self.last_update_ts = time.time()

    def get_snapshot(self, depth: int = 10) -> OrderBookSnapshot:
        """导出当前订单簿快照 (截取指定深度)"""
        ask_levels = [
            PriceLevel(price=p, size=s)
            for p, s in self.asks.items()[:depth]
        ]
        bid_levels = [
            PriceLevel(price=p, size=s)
            for p, s in self.bids.items(reverse=True)[:depth]
        ]

        return OrderBookSnapshot(
            token_id=self.token_id,
            condition_id=self.condition_id,
            timestamp=self.last_update_ts,
            asks=ask_levels,
            bids=bid_levels,
        )

    @property
    def best_ask(self) -> Optional[PriceLevel]:
        if not self.asks:
            return None
        price, size = self.asks.peekitem(0)
        return PriceLevel(price=price, size=size)

    @property
    def best_bid(self) -> Optional[PriceLevel]:
        if not self.bids:
            return None
        # bids SortedDict 也是升序, 最高价在最后
        price, size = self.bids.peekitem(-1)
        return PriceLevel(price=price, size=size)


class MarketDataGateway:
    """
    市场数据网关 (MDG)
    
    数据流:
    [Gamma API] → 市场发现 → [CLOB WS] → 订单簿增量 → 本地镜像 → Snapshot → SPE
    """

    def __init__(self, snapshot_callback: Callable[[OrderBookSnapshot], None]):
        self.cfg = CONFIG.gamma
        self.ws_cfg = CONFIG.clob

        # 回调: 每次订单簿更新时调用, 将 Snapshot 推给 SPE
        self.snapshot_callback = snapshot_callback

        # 市场注册表: condition_id -> MarketInfo
        self._markets: dict[str, MarketInfo] = {}

        # 订单簿镜像: token_id -> OrderBookMirror
        self._mirrors: dict[str, OrderBookMirror] = {}

        # WebSocket 会话
        self._ws_session: Optional[aiohttp.ClientSession] = None
        self._ws_connection: Optional[aiohttp.ClientWebSocketResponse] = None
        self._running: bool = False

        # 同一 condition_id 下的 YES/NO token 映射
        self._condition_to_tokens: dict[str, dict[str, str]] = {}

    # ================================================================
    # Phase 1: 市场发现 (Gamma API)
    # ================================================================

    async def discover_markets(self) -> list[MarketInfo]:
        """
        通过 Gamma API 轮询活跃市场
        筛选条件: active=True, volume >= min_volume, liquidity >= min_liquidity
        """
        url = f"{self.cfg.api_url}/markets"
        params = {
            "active": "true",
            "closed": "false",
            "order": "volume",
            "ascending": "false",
            "limit": 200,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        logger.error("gamma_api_error", status=resp.status)
                        return []

                    data = await resp.json()

        except Exception as e:
            logger.error("gamma_api_exception", error=str(e))
            return []

        markets = []
        for item in data:
            try:
                # 提取 YES / NO token IDs
                tokens = item.get("tokens", [])
                if len(tokens) < 2:
                    continue

                yes_token = ""
                no_token = ""
                for tok in tokens:
                    outcome = tok.get("outcome", "").upper()
                    if outcome == "YES":
                        yes_token = tok.get("token_id", "")
                    elif outcome == "NO":
                        no_token = tok.get("token_id", "")

                if not yes_token or not no_token:
                    continue

                volume = float(item.get("volume", 0) or 0)
                liquidity = float(item.get("liquidity", 0) or 0)

                # 流动性过滤
                if volume < self.cfg.min_volume or liquidity < self.cfg.min_liquidity:
                    continue

                market = MarketInfo(
                    condition_id=item.get("condition_id", ""),
                    question=item.get("question", ""),
                    yes_token_id=yes_token,
                    no_token_id=no_token,
                    active=item.get("active", True),
                    volume=volume,
                    liquidity=liquidity,
                    end_date_iso=item.get("end_date_iso", ""),
                )

                markets.append(market)
                self._markets[market.condition_id] = market
                self._condition_to_tokens[market.condition_id] = {
                    "yes": yes_token,
                    "no": no_token,
                }

            except Exception as e:
                logger.warning("market_parse_error", error=str(e), item=str(item)[:100])
                continue

        logger.info(
            "market_discovery_complete",
            total=len(data),
            filtered=len(markets),
        )
        return markets

    # ================================================================
    # Phase 1: 订单簿订阅 (CLOB WebSocket)
    # ================================================================

    async def subscribe_orderbooks(self, token_ids: list[str]) -> None:
        """
        建立 WebSocket 连接并订阅指定 token 的订单簿
        
        协议:
        1. 连接 wss://ws-subscriptions-clob.polymarket.com/ws
        2. 发送订阅消息: {"auth":{}, "markets":[token_ids], "type":"market"}
        3. 接收增量推送并更新本地镜像
        """
        self._running = True

        # 为每个 token 创建本地镜像
        for token_id in token_ids:
            condition_id = self._find_condition_by_token(token_id)
            mirror = OrderBookMirror(token_id=token_id, condition_id=condition_id)
            self._mirrors[token_id] = mirror

        retry_count = 0
        max_retries = 10

        while self._running and retry_count < max_retries:
            try:
                await self._ws_connect_and_listen(token_ids)
                retry_count = 0  # 连接成功, 重置计数
            except Exception as e:
                retry_count += 1
                delay = min(2 ** retry_count, 60)  # 指数退避, 最大 60s
                logger.error(
                    "ws_connection_failed",
                    error=str(e),
                    retry=retry_count,
                    reconnect_in=delay,
                )
                await asyncio.sleep(delay)

        logger.warning("mdg_ws_stopped", reason="max_retries_exceeded")

    async def _ws_connect_and_listen(self, token_ids: list[str]) -> None:
        """建立 WebSocket 连接并处理消息"""
        self._ws_session = aiohttp.ClientSession()

        try:
            self._ws_connection = await self._ws_session.ws_connect(
                self.ws_cfg.ws_url,
                heartbeat=30,
                receive_timeout=60,
            )
            logger.info("ws_connected", url=self.ws_cfg.ws_url)

            # 发送订阅请求
            subscribe_msg = {
                "auth": {},
                "markets": token_ids,
                "type": "market",
            }
            await self._ws_connection.send_json(subscribe_msg)
            logger.info("ws_subscribed", token_count=len(token_ids))

            # 消息监听循环
            async for msg in self._ws_connection:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_ws_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error("ws_error", error=msg.data)
                    break
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                    break

                if not self._running:
                    break

        finally:
            if self._ws_connection and not self._ws_connection.closed:
                await self._ws_connection.close()
            if self._ws_session and not self._ws_session.closed:
                await self._ws_session.close()

    async def _handle_ws_message(self, raw_data: str) -> None:
        """
        处理 WebSocket 推送消息
        
        消息类型:
        - price_change: 增量价格变动
        - book_snapshot: 全量订单簿快照
        """
        try:
            data = json.loads(raw_data)
        except json.JSONDecodeError:
            logger.warning("ws_invalid_json", raw=raw_data[:200])
            return

        event_type = data.get("event_type", data.get("type", ""))

        if event_type == "price_change":
            await self._apply_delta_update(data)
        elif event_type in ("book_snapshot", "snapshot"):
            await self._apply_snapshot_update(data)

    async def _apply_snapshot_update(self, data: dict) -> None:
        """处理全量快照推送"""
        token_id = data.get("asset_id", data.get("token_id", ""))
        mirror = self._mirrors.get(token_id)

        if not mirror:
            return

        asks_raw = data.get("asks", [])
        bids_raw = data.get("bids", [])

        # 将嵌套列表转为标准格式
        asks = self._normalize_book_levels(asks_raw)
        bids = self._normalize_book_levels(bids_raw)

        mirror.apply_snapshot(asks=asks, bids=bids)

        # 推送给 SPE
        snapshot = mirror.get_snapshot()
        self.snapshot_callback(snapshot)

    async def _apply_delta_update(self, data: dict) -> None:
        """处理增量价格变动推送"""
        token_id = data.get("asset_id", data.get("token_id", ""))
        mirror = self._mirrors.get(token_id)

        if not mirror:
            return

        changes = data.get("changes", data.get("price_changes", []))

        for change in changes:
            price = float(change.get("price", 0))
            size = float(change.get("size", 0))
            side = change.get("side", "sell")   # "sell" = ask, "buy" = bid

            mirror.apply_delta(price=price, size=size, side=side)

        # 推送给 SPE
        snapshot = mirror.get_snapshot()
        self.snapshot_callback(snapshot)

    def _normalize_book_levels(self, levels: list) -> list[dict]:
        """
        标准化订单簿层级数据
        Polymarket 可返回 [[price, size], ...] 或 [{"price":x, "size":y}, ...]
        """
        result = []
        for level in levels:
            if isinstance(level, (list, tuple)):
                if len(level) >= 2:
                    result.append({"price": float(level[0]), "size": float(level[1])})
            elif isinstance(level, dict):
                result.append({"price": float(level.get("price", 0)), "size": float(level.get("size", 0))})
        return result

    def _find_condition_by_token(self, token_id: str) -> str:
        """通过 token_id 反查 condition_id"""
        for cid, tokens in self._condition_to_tokens.items():
            if token_id in tokens.values():
                return cid
        return ""

    # ================================================================
    # 订阅管理
    # ================================================================

    async def start_market_discovery_loop(self) -> None:
        """定期发现市场的后台任务"""
        while self._running:
            markets = await self.discover_markets()
            if markets:
                token_ids = []
                for m in markets:
                    token_ids.extend([m.yes_token_id, m.no_token_id])
                logger.info("market_tokens_ready", count=len(token_ids))

                # 如果 WS 尚未运行, 启动订阅
                if not self._mirrors:
                    asyncio.create_task(self.subscribe_orderbooks(token_ids))

            await asyncio.sleep(self.cfg.poll_interval)

    async def stop(self) -> None:
        """优雅关闭"""
        self._running = False
        if self._ws_connection and not self._ws_connection.closed:
            await self._ws_connection.close()
        if self._ws_session and not self._ws_session.closed:
            await self._ws_session.close()
        logger.info("mdg_stopped")
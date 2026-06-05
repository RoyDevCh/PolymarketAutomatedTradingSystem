"""
Polymarket 自动套利系统 - 市场数据网关 (MDG)

职责:
1. 通过 Gamma API 定期发现活跃市场
2. 建立 Market Channel WebSocket 长连接, 订阅实时订单簿
3. 在本地内存中维护增量订单簿镜像 (REST 快照 + WS 增量)
4. 向下游 SPE 推送 BBO / 完整快照

v1.1 修正:
  - Market Channel 订阅协议修正为官方规格:
    assets_ids (非 markets), type="market", custom_feature_enabled
  - 事件类型: book / price_change / last_trade_price / tick_size_change
  - 心跳: 客户端每 10s 发送 PING
  - 重连后先 REST 快照再 WS 订阅, 避免增量遗漏
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
from core.clob_client import get_clob_client
from core.models import MarketInfo, OrderBookSnapshot, PriceLevel

# ============================================================
# 代理配置: 自动检测 mihomo/Clash 本地代理
# 从环境变量 http_proxy / https_proxy 读取
# ============================================================
def _get_proxy_url() -> str | None:
    """获取代理 URL, 支持环境变量和 .proxyrc"""
    import os
    return os.environ.get("https_proxy") or os.environ.get("http_proxy") or None

_PROXY_URL = _get_proxy_url()

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
            for p, s in list(reversed(self.bids.items()))[:depth]
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
        self._ws_heartbeat_task: Optional[asyncio.Task] = None
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
            async with aiohttp.ClientSession(trust_env=True) as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15), proxy=_PROXY_URL) as resp:
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
                # v1.1: 适配 Gamma API 实际返回格式
                # condition_id 字段: conditionId (驼峰) 或 condition_id
                condition_id = item.get("conditionId", "") or item.get("condition_id", "")
                if not condition_id:
                    continue

                # token IDs 优先从 clobTokenIds 提取, 其次从 tokens 数组
                yes_token = ""
                no_token = ""

                # clobTokenIds 可能是 JSON 字符串而非列表
                clob_token_ids = item.get("clobTokenIds", [])
                if isinstance(clob_token_ids, str):
                    try:
                        clob_token_ids = json.loads(clob_token_ids)
                    except (json.JSONDecodeError, TypeError):
                        clob_token_ids = []

                # outcomes 也可能是 JSON 字符串
                outcomes = item.get("outcomes", [])
                if isinstance(outcomes, str):
                    try:
                        outcomes = json.loads(outcomes)
                    except (json.JSONDecodeError, TypeError):
                        outcomes = []
                if isinstance(clob_token_ids, list) and len(clob_token_ids) >= 2:
                    for i, tid in enumerate(clob_token_ids):
                        if i < len(outcomes):
                            outcome = str(outcomes[i]).upper()
                            if outcome == "YES":
                                yes_token = tid
                            elif outcome == "NO":
                                no_token = tid
                    # 如果 outcomes 为空, 顺序推断: 第一个=YES, 第二个=NO
                    if not yes_token and len(clob_token_ids) >= 2:
                        yes_token = clob_token_ids[0]
                        no_token = clob_token_ids[1]

                # 方式 2: tokens 数组 (旧格式)
                if not yes_token or not no_token:
                    tokens = item.get("tokens", [])
                    if isinstance(tokens, list):
                        for tok in tokens:
                            outcome = str(tok.get("outcome", "")).upper()
                            if outcome == "YES":
                                yes_token = tok.get("token_id", "")
                            elif outcome == "NO":
                                no_token = tok.get("token_id", "")

                if not yes_token or not no_token:
                    continue

                # volume/liquidity: 优先 volumeNum/liquidityNum, 其次 volume/liquidity
                volume = float(item.get("volumeNum", 0) or item.get("volume", 0) or 0)
                liquidity = float(item.get("liquidityNum", 0) or item.get("liquidity", 0) or item.get("liquidityClob", 0) or 0)

                # 流动性过滤
                if volume < self.cfg.min_volume:
                    continue
                # liquidity 可以为 0 但 volume 合格
                # if liquidity < self.cfg.min_liquidity:
                #     continue

                question = item.get("question", "")[:200]

                market = MarketInfo(
                    condition_id=condition_id,
                    question=question,
                    yes_token_id=yes_token,
                    no_token_id=no_token,
                    active=item.get("active", True),
                    volume=volume,
                    liquidity=liquidity,
                    end_date_iso=item.get("endDateIso", "") or item.get("end_date_iso", ""),
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
        建立 Market Channel WebSocket 连接并订阅实时订单簿
        
        协议 (官方规格 2026-04 CLOB V2):
        1. 首先通过 REST API 获取初始快照
        2. 连接 wss://ws-subscriptions-clob.polymarket.com/ws/market
        3. 发送订阅消息:
           {"assets_ids": ["token_id_1", ...],
            "type": "market",
            "custom_feature_enabled": true}
        4. 接收增量推送并更新本地镜像
        5. 客户端每 10s 发送 PING 心跳
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
        """建立 Market Channel WebSocket 连接并处理消息"""
        # v1.1: 使用官方 Market Channel 端点
        ws_url = self.ws_cfg.ws_market_url

        self._ws_session = aiohttp.ClientSession(trust_env=True)

        try:
            self._ws_connection = await self._ws_session.ws_connect(
                ws_url,
                heartbeat=30,
                receive_timeout=60,
                proxy=_PROXY_URL,
            )
            logger.info("mdg_ws_connected", url=ws_url)

            # v1.1: 使用官方规格的订阅格式
            subscribe_msg = {
                "assets_ids": token_ids,
                "type": "market",
                "custom_feature_enabled": True,  # 启用 best_bid_ask / tick_size_change 等事件
            }
            await self._ws_connection.send_json(subscribe_msg)
            logger.info("mdg_ws_subscribed", token_count=len(token_ids))

            # v1.1: 启动心跳任务 (每10秒发送PING)
            self._ws_heartbeat_task = asyncio.create_task(
                self._ws_heartbeat(), name="mdg_heartbeat"
            )

            # 重连后先 REST 拉取快照再监听增量
            await self._fetch_rest_snapshots(token_ids)

            # 消息监听循环
            async for msg in self._ws_connection:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    if msg.data == "PONG":
                        continue  # 心跳响应, 跳过
                    await self._handle_ws_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error("mdg_ws_error", error=msg.data)
                    break
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                    break

                if not self._running:
                    break

        finally:
            if hasattr(self, '_ws_heartbeat_task') and self._ws_heartbeat_task:
                self._ws_heartbeat_task.cancel()
            if self._ws_connection and not self._ws_connection.closed:
                await self._ws_connection.close()
            if self._ws_session and not self._ws_session.closed:
                await self._ws_session.close()

    async def _ws_heartbeat(self) -> None:
        """Market Channel 心跳: 每 10 秒发送 PING"""
        while self._running:
            try:
                if self._ws_connection and not self._ws_connection.closed:
                    await self._ws_connection.send_str("PING")
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("mdg_heartbeat_error", error=str(e))
                break

    async def _fetch_rest_snapshots(self, token_ids: list[str]) -> None:
        """
        v1.1: 重连后通过 REST API 拉取初始快照
        确保增量更新不会基于过时的订单簿
        
        v1.3: 适配 V2 SDK dict 返回格式
        """
        client = None
        try:
            client = get_clob_client()
        except Exception:
            logger.warning("mdg_rest_snapshot_client_unavailable")
            return

        for token_id in token_ids:
            try:
                book = client.get_order_book(token_id)
                if book and token_id in self._mirrors:
                    # V2 SDK returns dict, not object with .asks/.bids
                    if isinstance(book, dict):
                        asks_raw = book.get("asks", []) or []
                        bids_raw = book.get("bids", []) or []
                    else:
                        asks_raw = book.asks if hasattr(book, "asks") else []
                        bids_raw = book.bids if hasattr(book, "bids") else []
                    asks = [{"price": float(a.get("price", 0) if isinstance(a, dict) else getattr(a, "price", 0)),
                             "size": float(a.get("size", 0) if isinstance(a, dict) else getattr(a, "size", 0))}
                            for a in (asks_raw or [])]
                    bids = [{"price": float(b.get("price", 0) if isinstance(b, dict) else getattr(b, "price", 0)),
                             "size": float(b.get("size", 0) if isinstance(b, dict) else getattr(b, "size", 0))}
                            for b in (bids_raw or [])]
                    self._mirrors[token_id].apply_snapshot(asks=asks, bids=bids)
                    logger.debug("mdg_rest_snapshot_loaded", token_id=token_id[:16])
            except Exception as e:
                logger.warning("mdg_rest_snapshot_error", token_id=token_id[:16], error=str(e)[:80])

    async def _handle_ws_message(self, raw_data: str) -> None:
        """
        处理 WebSocket 推送消息
        
        v1.2 修正: WS 可能发送 JSON 数组 (多个事件) 或单个对象
        """
        try:
            parsed = json.loads(raw_data)
        except json.JSONDecodeError:
            logger.warning("mdg_ws_invalid_json", raw=raw_data[:200])
            return

        # 归一化: 无论是对象还是数组, 都转为事件列表
        events = parsed if isinstance(parsed, list) else [parsed]

        # v1.3: 数据流确认 (前 10 次 INFO, 后续每 500 次)
        if not hasattr(self, '_ws_event_count'):
            self._ws_event_count = 0
        self._ws_event_count += len(events)
        if self._ws_event_count <= 10 or self._ws_event_count % 500 == 0:
            ev_types = [d.get('event_type', d.get('type', '?')) for d in events[:3]]
            logger.info(
                'mdg_ws_event',
                types=ev_types,
                total=self._ws_event_count,
            )

        for data in events:
            event_type = data.get("event_type", data.get("type", ""))

            if event_type == "book":
                await self._apply_snapshot_update(data)
            elif event_type == "price_change":
                await self._apply_delta_update(data)
            elif event_type == "last_trade_price":
                self._handle_last_trade(data)
            elif event_type == "tick_size_change":
                self._handle_tick_size_change(data)
            elif event_type == "best_bid_ask":
                self._handle_best_bid_ask(data)
            elif event_type == "new_market":
                logger.debug("mdg_new_market", question=data.get("question", "")[:50])
            else:
                logger.debug("mdg_ws_unknown_event", event_type=event_type)

    async def _apply_snapshot_update(self, data: dict) -> None:
        """处理全量快照推送 (event_type='book')"""
        token_id = data.get("asset_id", data.get("token_id", ""))
        mirror = self._mirrors.get(token_id)

        if not mirror:
            return

        asks_raw = data.get("asks", [])
        bids_raw = data.get("bids", [])

        asks = self._normalize_book_levels(asks_raw)
        bids = self._normalize_book_levels(bids_raw)

        mirror.apply_snapshot(asks=asks, bids=bids)

        # 推送给 SPE
        snapshot = mirror.get_snapshot()
        self.snapshot_callback(snapshot)

    def _handle_last_trade(self, data: dict) -> None:
        """处理最新成交价事件"""
        token_id = data.get("asset_id", "")
        price = data.get("price", "")
        size = data.get("size", "")
        side = data.get("side", "")
        logger.debug(
            "mdg_last_trade",
            token_id=token_id[:16] if token_id else "N/A",
            price=price,
            size=size,
            side=side,
        )

    def _handle_tick_size_change(self, data: dict) -> None:
        """
        处理 tick_size 变化事件
        ⚠️ 关键: 如果 tick_size 变化, 需要更新下单时使用的最小价格精度
        """
        token_id = data.get("asset_id", "")
        old_tick = data.get("old_tick_size", "")
        new_tick = data.get("new_tick_size", "")
        logger.info(
            "mdg_tick_size_change",
            token_id=token_id[:16] if token_id else "N/A",
            old=old_tick,
            new=new_tick,
        )

    def _handle_best_bid_ask(self, data: dict) -> None:
        """
        处理最优买卖价更新事件 (需 custom_feature_enabled=True)
        用作快速 BBO 更新, 无需等待完整 book 快照
        """
        # price_changes 可能包含多个 token 的更新
        changes = data.get("price_changes", [])
        for change in changes:
            token_id = change.get("asset_id", "")
            best_bid = change.get("best_bid")
            best_ask = change.get("best_ask")
            if token_id and best_bid and best_ask and token_id in self._mirrors:
                # 快速 BBO 更新 (不重建完整订单簿)
                logger.debug(
                    "mdg_best_bid_ask",
                    token_id=token_id[:16],
                    best_bid=best_bid,
                    best_ask=best_ask,
                )

    async def _apply_delta_update(self, data: dict) -> None:
        """
        处理增量价格变动推送 (event_type='price_change')
        
        v1.1 修正: price_changes 是列表, 每个 change 包含:
          - asset_id: token ID
          - price: 价格
          - size: 数量 ("0" 表示删除该档位)
          - side: BUY / SELL
          - best_bid / best_ask: 最优买卖价 (可选)
        """
        # price_change 事件可能包含多个 token 的更新
        changes = data.get("price_changes", [])
        if not changes:
            # 兼容旧格式: 单一 token 的变更
            changes = [{
                "asset_id": data.get("asset_id", ""),
                "price": data.get("price", 0),
                "size": data.get("size", 0),
                "side": data.get("side", "sell"),
            }]

        for change in changes:
            token_id = change.get("asset_id", "")
            mirror = self._mirrors.get(token_id)

            if not mirror:
                continue

            price = float(change.get("price", 0))
            size = float(change.get("size", 0))
            # v1.1: side 字段使用 BUY / SELL (大写)
            side_raw = change.get("side", "SELL").upper()
            side = "sell" if side_raw == "SELL" else "buy"

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
        self._running = True  # 启动主循环
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
        if self._ws_heartbeat_task and not self._ws_heartbeat_task.done():
            self._ws_heartbeat_task.cancel()
        if self._ws_connection and not self._ws_connection.closed:
            await self._ws_connection.close()
        if self._ws_session and not self._ws_session.closed:
            await self._ws_session.close()
        logger.info("mdg_stopped")
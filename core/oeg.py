"""
Polymarket 自动套利系统 - 订单执行网关 (OEG)

职责:
1. 从信号队列消费 TradeSignal
2. 构造 OrderArgs + EIP-712 签名 (通过 py-clob-client)
3. asyncio.gather 并发下发 YES/NO 双腿订单, 消除 Leg Risk
4. 通过 User Channel WebSocket 实时监听撮合回执
5. 向 RMC 报告执行结果

v1.1 重写: 完整实现 User Channel WebSocket 私有频道,
         替代 HTTP 轮询实现毫秒级撮合确认
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Callable, Optional

import aiohttp
import structlog

from core.config import CONFIG
from core.clob_client import get_clob_client
from core.models import (
    ArbitrageResult,
    CircuitBreakerType,
    ExecutionResult,
    OrderRequest,
    OrderStatus,
    OrderType,
    Side,
    TradeSignal,
)

# 代理配置
import os
_PROXY_URL = os.environ.get("https_proxy") or os.environ.get("http_proxy") or None

logger = structlog.get_logger(__name__)


# ============================================================
# User Channel WebSocket 撮合回执监听器
# ============================================================

class FillTracker:
    """
    通过 Polymarket User Channel WebSocket 实时追踪订单撮合状态

    协议规格:
    ┌──────────────────────────────────────────────────────┐
    │  Endpoint: wss://ws-subscriptions-clob.polymarket.com/ws/user │
    │  认证: 在订阅消息中提供 apiKey/secret/passphrase     │
    │  心跳: 每 10 秒发送 PING, 服务端响应 PONG            │
    │                                                        │
    │  Trade 状态机:                                         │
    │    MATCHED → MINED → CONFIRMED (终态成功)             │
    │    MATCHED → RETRYING → CONFIRMED (重试后成功)        │
    │    MATCHED → RETRYING → FAILED   (终态失败)           │
    │                                                        │
    │  Order 状态机:                                         │
    │    PLACEMENT → UPDATE (部分成交) → 取消或全成          │
    │    PLACEMENT → CANCELLATION                            │
    └──────────────────────────────────────────────────────┘
    """

    def __init__(
        self,
        on_order_matched: Optional[Callable] = None,
        on_trade_confirmed: Optional[Callable] = None,
        on_trade_failed: Optional[Callable] = None,
    ):
        self.cfg = CONFIG.clob

        # 回调函数
        self._on_order_matched = on_order_matched
        self._on_trade_confirmed = on_trade_confirmed
        self._on_trade_failed = on_trade_failed

        # 待追踪的订单: order_id -> OrderTracker
        self._pending_orders: dict[str, OrderTracker] = {}

        # WebSocket 连接
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._running = False

        # 心跳任务
        self._heartbeat_task: Optional[asyncio.Task] = None

    def track_order(
        self,
        order_id: str,
        signal_id: str,
        token_id: str,
        side: Side,
        expected_size: float,
        expected_price: float,
        condition_id: str = "",
    ) -> None:
        """注册一个待追踪的订单"""
        self._pending_orders[order_id] = OrderTracker(
            order_id=order_id,
            signal_id=signal_id,
            token_id=token_id,
            side=side,
            expected_size=expected_size,
            expected_price=expected_price,
            condition_id=condition_id,
        )
        logger.debug(
            "fill_tracker_register",
            order_id=order_id[:16],
            side=side.value,
            size=expected_size,
        )

    def subscribe_condition(self, condition_id: str) -> None:
        """动态订阅新的市场条件 (无需重连)"""
        if self._ws and not self._ws.closed:
            msg = {
                "markets": [condition_id],
                "operation": "subscribe",
            }
            asyncio.create_task(self._ws.send_json(msg))
            logger.info("fill_tracker_subscribe", condition=condition_id[:16])

    async def start(self, condition_ids: list[str] = None) -> None:
        """启动 User Channel WebSocket 监听"""
        self._running = True
        condition_ids = condition_ids or []

        retry_count = 0
        max_retries = 15

        while self._running and retry_count < max_retries:
            try:
                await self._connect_and_listen(condition_ids)
                retry_count = 0  # 连接成功重置
            except Exception as e:
                retry_count += 1
                delay = min(2 ** retry_count, 60)
                logger.error(
                    "fill_tracker_ws_error",
                    error=str(e),
                    retry=retry_count,
                    reconnect_in=delay,
                )
                await asyncio.sleep(delay)

        logger.warning("fill_tracker_stopped", reason="max_retries_exceeded")

    async def stop(self) -> None:
        """停止监听"""
        self._running = False
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("fill_tracker_stopped")

    # ============================================================
    # WebSocket 连接与认证
    # ============================================================

    async def _connect_and_listen(self, condition_ids: list[str]) -> None:
        """建立认证连接并监听事件"""
        self._session = aiohttp.ClientSession(trust_env=True)

        try:
            self._ws = await self._session.ws_connect(
                f"{self.cfg.ws_user_url}",
                heartbeat=30,
                receive_timeout=60,
                proxy=_PROXY_URL,
            )
            logger.info("fill_tracker_ws_connected")

            # 发送认证 + 订阅消息
            auth_msg = {
                "auth": {
                    "apiKey": self.cfg.api_key,
                    "secret": self.cfg.api_secret,
                    "passphrase": self.cfg.api_passphrase,
                },
                "markets": condition_ids,
                "type": "user",
            }
            await self._ws.send_json(auth_msg)
            logger.info("fill_tracker_authenticated", markets=len(condition_ids))

            # 启动心跳
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            # 消息监听循环
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    if msg.data == "PONG":
                        continue
                    await self._handle_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error("fill_tracker_ws_error", error=msg.data)
                    break
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                    break

                if not self._running:
                    break

        finally:
            if self._heartbeat_task and not self._heartbeat_task.done():
                self._heartbeat_task.cancel()
            if self._ws and not self._ws.closed:
                await self._ws.close()
            if self._session and not self._session.closed:
                await self._session.close()

    async def _heartbeat_loop(self) -> None:
        """每 10 秒发送 PING 心跳"""
        while self._running:
            try:
                if self._ws and not self._ws.closed:
                    await self._ws.send_str("PING")
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("fill_tracker_heartbeat_error", error=str(e))
                break

    # ============================================================
    # 消息处理
    # ============================================================

    async def _handle_message(self, raw: str) -> None:
        """处理 User Channel 推送消息"""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        event_type = data.get("event_type", "")

        if event_type == "trade":
            await self._handle_trade_event(data)
        elif event_type == "order":
            await self._handle_order_event(data)

    async def _handle_trade_event(self, data: dict) -> None:
        """
        处理 Trade 事件

        状态机:
          MATCHED  → 订单已匹配, 等待上链
          MINED    → 已上链, 等待确认
          CONFIRMED → 终态: 交易成功
          FAILED   → 终态: 交易失败
        """
        trade_id = data.get("id", "")
        order_id = data.get("taker_order_id", "")
        status = data.get("status", "")
        asset_id = data.get("asset_id", "")
        size = float(data.get("size", "0"))
        price = float(data.get("price", "0"))
        timestamp = data.get("timestamp", "")

        # 尝试关联到已知订单
        tracker = self._find_tracker(order_id, asset_id)

        if status == "MATCHED":
            logger.info(
                "TRADE_MATCHED",
                trade_id=trade_id[:16] if trade_id else "N/A",
                order_id=order_id[:16] if order_id else "N/A",
                size=size,
                price=price,
            )
            if tracker:
                tracker.matched_size = size
                tracker.matched_price = price
                tracker.status = OrderStatus.MATCHED

                if self._on_order_matched:
                    self._on_order_matched(tracker)

        elif status == "CONFIRMED":
            logger.info(
                "TRADE_CONFIRMED",
                trade_id=trade_id[:16] if trade_id else "N/A",
                order_id=order_id[:16] if order_id else "N/A",
                size=size,
                price=price,
            )
            if tracker:
                tracker.confirmed_size = size
                tracker.confirmed_price = price
                tracker.status = OrderStatus.MATCHED

                if self._on_trade_confirmed:
                    self._on_trade_confirmed(tracker)

        elif status == "FAILED":
            logger.error(
                "TRADE_FAILED",
                trade_id=trade_id[:16] if trade_id else "N/A",
                order_id=order_id[:16] if order_id else "N/A",
            )
            if tracker:
                tracker.status = OrderStatus.FAILED

                if self._on_trade_failed:
                    self._on_trade_failed(tracker)

        elif status == "RETRYING":
            logger.warning(
                "TRADE_RETRYING",
                trade_id=trade_id[:16] if trade_id else "N/A",
                order_id=order_id[:16] if order_id else "N/A",
            )

    async def _handle_order_event(self, data: dict) -> None:
        """
        处理 Order 事件

        类型:
          PLACEMENT    → 订单已挂出
          UPDATE       → 部分成交更新
          CANCELLATION → 订单已取消
        """
        order_id = data.get("id", "")
        event_type_detail = data.get("type", "")  # PLACEMENT / UPDATE / CANCELLATION
        size_matched = float(data.get("size_matched", "0"))
        original_size = float(data.get("original_size", "0"))
        status = data.get("status", "")
        asset_id = data.get("asset_id", "")

        tracker = self._pending_orders.get(order_id)

        if event_type_detail == "PLACEMENT":
            logger.debug(
                "ORDER_PLACED",
                order_id=order_id[:16] if order_id else "N/A",
                original_size=original_size,
                status=status,
            )

        elif event_type_detail == "UPDATE":
            if tracker:
                tracker.matched_size = size_matched
                logger.debug(
                    "ORDER_PARTIAL_FILL",
                    order_id=order_id[:16] if order_id else "N/A",
                    matched=size_matched,
                    original=original_size,
                )

        elif event_type_detail == "CANCELLATION":
            logger.info(
                "ORDER_CANCELLED",
                order_id=order_id[:16] if order_id else "N/A",
            )
            if tracker:
                tracker.status = OrderStatus.CANCELLED
                # 不立即移除 tracker, 让 OEG 通过 _try_complete_arbitrage 处理
                # 移除时机: OEG 调用 remove_tracker() 或超时清理

    def _find_tracker(self, order_id: str, asset_id: str) -> Optional["OrderTracker"]:
        """通过 order_id 或 asset_id 查找追踪器"""
        tracker = self._pending_orders.get(order_id)
        if tracker:
            return tracker

        # 降级: 通过 asset_id (token_id) 匹配
        for oid, t in self._pending_orders.items():
            if t.token_id == asset_id:
                return t

        return None

    def get_tracker(self, order_id: str) -> Optional["OrderTracker"]:
        """获取指定订单的追踪状态"""
        return self._pending_orders.get(order_id)

    def remove_tracker(self, order_id: str) -> None:
        """移除已完成的追踪器"""
        self._pending_orders.pop(order_id, None)


class OrderTracker:
    """订单追踪数据"""
    __slots__ = (
        "order_id", "signal_id", "token_id", "side",
        "expected_size", "expected_price", "condition_id",
        "matched_size", "matched_price", "confirmed_size", "confirmed_price",
        "status", "created_at",
    )

    def __init__(
        self,
        order_id: str,
        signal_id: str,
        token_id: str,
        side: Side,
        expected_size: float,
        expected_price: float,
        condition_id: str = "",
    ):
        self.order_id = order_id
        self.signal_id = signal_id
        self.token_id = token_id
        self.side = side
        self.expected_size = expected_size
        self.expected_price = expected_price
        self.condition_id = condition_id
        self.matched_size: float = 0.0
        self.matched_price: float = 0.0
        self.confirmed_size: float = 0.0
        self.confirmed_price: float = 0.0
        self.status: OrderStatus = OrderStatus.PENDING
        self.created_at: float = time.time()


# ============================================================
# 订单执行网关
# ============================================================

class OrderExecutionGateway:
    """
    订单执行网关 (OEG)

    核心原则:
    ┌──────────────────────────────────────────────────┐
    │  ⚠️  严禁串行下单!                                  │
    │                                                     │
    │  YES 和 NO 订单必须使用 asyncio.gather 并发       │
    │  发出, 最大限度降低单边敞口风险 (Leg Risk)          │
    │                                                     │
    │  时间差 = |t_yes - t_no| 应 < 50ms                  │
    └──────────────────────────────────────────────────┘

    v1.1 升级:
    - 集成 FillTracker 实现毫秒级撮合确认
    - 支持 MATCHED/CONFIRMED/FAILED 状态实时回调
    - 双腿终态判定后自动触发 RMC 结果回调
    """

    def __init__(
        self,
        result_callback: Callable,
        circuit_breaker_callback: Callable,
        fill_update_callback: Callable | None = None,
    ):
        self.cfg = CONFIG.clob
        self.trading_cfg = CONFIG.trading

        # 回调函数
        self._result_callback = result_callback
        self._circuit_breaker_callback = circuit_breaker_callback
        self._fill_update_callback = fill_update_callback

        # CLOB Client (惰性初始化)
        self._client = None

        # 进行中的套利: signal_id -> ArbitrageResult
        self._pending: dict[str, ArbitrageResult] = {}

        # 已禁用的市场 (由风控触发)
        self._disabled_markets: set[str] = set()

        # 撮合追踪器
        self._fill_tracker: Optional[FillTracker] = None

        # 执行统计
        self._stats = {
            "signals_received": 0,
            "orders_sent": 0,
            "orders_matched": 0,
            "orders_confirmed": 0,
            "orders_failed": 0,
            "leg_risk_count": 0,
        }

    def _get_client(self):
        """惰性获取 CLOB Client"""
        if self._client is None:
            self._client = get_clob_client()
        return self._client

    def _on_order_matched(self, tracker: OrderTracker) -> None:
        """FillTracker 回调: 订单被撮合"""
        self._stats["orders_matched"] += 1
        logger.info(
            "oeg_order_matched_ws",
            signal_id=tracker.signal_id[:8],
            order_id=tracker.order_id[:16],
            side=tracker.side.value,
            size=tracker.matched_size,
            price=tracker.matched_price,
        )

        # 尝试完成 ArbitrageResult
        self._try_complete_arbitrage(tracker.signal_id)

    def _on_trade_confirmed(self, tracker: OrderTracker) -> None:
        """FillTracker callback: on-chain trade confirmed."""
        self._stats["orders_confirmed"] += 1
        logger.info(
            "oeg_trade_confirmed_ws",
            signal_id=tracker.signal_id[:8],
            order_id=tracker.order_id[:16],
            side=tracker.side.value,
            size=tracker.confirmed_size,
            price=tracker.confirmed_price,
        )
        meta = self._pending.get(tracker.signal_id)
        if meta and getattr(meta, "yes_result", None):
            exp_yes = meta.yes_result.price
            exp_no = meta.no_result.price
            exp = exp_yes if tracker.side == Side.YES else exp_no
            if exp and tracker.confirmed_price:
                slip = abs(tracker.confirmed_price - exp)
                if slip > 0.001:
                    logger.warning(
                        "SLIPPAGE_DEVIATION",
                        signal_id=tracker.signal_id[:8],
                        side=tracker.side.value,
                        expected=exp,
                        actual=tracker.confirmed_price,
                        deviation=slip,
                    )
        if self._fill_update_callback:
            asyncio.create_task(
                self._fill_update_callback(
                    tracker.signal_id,
                    tracker.side.value,
                    tracker.confirmed_price,
                    tracker.confirmed_size,
                    "CONFIRMED",
                )
            )

    def _on_trade_failed(self, tracker: OrderTracker) -> None:
        """FillTracker 回调: 交易失败"""
        self._stats["orders_failed"] += 1
        logger.error(
            "oeg_trade_failed_ws",
            signal_id=tracker.signal_id[:8],
            order_id=tracker.order_id[:16],
            side=tracker.side.value,
        )

        # 标记对应腿为 FAILED
        result = self._pending.get(tracker.signal_id)
        if result:
            if tracker.side == Side.YES:
                result.yes_result.status = OrderStatus.FAILED
                result.yes_result.error_message = "Trade FAILED on-chain"
            else:
                result.no_result.status = OrderStatus.FAILED
                result.no_result.error_message = "Trade FAILED on-chain"

            # 检查是否触发 Leg Risk
            if result.has_leg_risk and self._circuit_breaker_callback:
                self._circuit_breaker_callback(tracker.condition_id)

    def _try_complete_arbitrage(self, signal_id: str) -> None:
        """
        当一根腿被 MATCHED 时, 检查双腿是否都已终态,
        如果是则触发 RMC 回调
        """
        result = self._pending.get(signal_id)
        if not result or not result.is_complete:
            return

        # 已经回调过则跳过
        yes_done = result.yes_result.status in (
            OrderStatus.MATCHED, OrderStatus.FAILED, OrderStatus.CANCELLED
        )
        no_done = result.no_result.status in (
            OrderStatus.MATCHED, OrderStatus.FAILED, OrderStatus.CANCELLED
        )

        if yes_done and no_done:
            # 计算实际盈亏
            if result.yes_result.status == OrderStatus.MATCHED and result.no_result.status == OrderStatus.MATCHED:
                total_cost = (
                    result.yes_result.avg_fill_price * result.yes_result.filled_size
                    + result.no_result.avg_fill_price * result.no_result.filled_size
                )
                total_payout = min(result.yes_result.filled_size, result.no_result.filled_size)
                result.realized_profit = total_payout - total_cost

            # 回调 RMC
            if self._result_callback:
                asyncio.create_task(self._result_callback(result))

            # 清理
            self._pending.pop(signal_id, None)

    # ============================================================
    # 主执行循环
    # ============================================================

    async def execution_loop(self, signal_queue: asyncio.Queue) -> None:
        """
        后台任务: 从信号队列持续消费并执行
        """
        logger.info("oeg_execution_loop_started")

        # 启动 FillTracker
        self._fill_tracker = FillTracker(
            on_order_matched=self._on_order_matched,
            on_trade_confirmed=self._on_trade_confirmed,
            on_trade_failed=self._on_trade_failed,
        )
        # FillTracker 需要订阅的 condition_ids, 在首次信号时动态添加
        fill_tracker_task = asyncio.create_task(
            self._fill_tracker.start(condition_ids=[]),
            name="fill_tracker",
        )

        # 在 DRY_RUN 模式下启动虚拟成交追踪
        self._virtual_orders = {}
        self._maker_stale_seconds = int(os.getenv("MAKER_STALE_SECONDS", "30"))
        # Stale order sweeper: auto-cancel Maker orders after N seconds
        if not CONFIG.flags.dry_run:
            asyncio.create_task(
                self._maker_stale_sweeper_loop(),
                name="maker_stale_sweeper",
            )
            logger.info("oeg_stale_sweeper_started", stale_seconds=self._maker_stale_seconds)
        if CONFIG.flags.dry_run:
            asyncio.create_task(
                self._virtual_fill_tracker_loop(),
                name="virtual_fill_tracker",
            )
            logger.info("oeg_virtual_fill_tracker_started")

        while True:
            try:
                signal: TradeSignal = await signal_queue.get()
                self._stats["signals_received"] += 1

                # 检查该市场是否被熔断禁用
                if signal.condition_id in self._disabled_markets:
                    logger.warning(
                        "oeg_market_disabled_skipping",
                        condition_id=signal.condition_id[:16],
                    )
                    continue

                # ── 并发敞口上限检查 (防止资金碎片化 + 单腿风险) ──
                active_conditions = set()
                for pending_result in self._pending.values():
                    if not pending_result.is_complete:  # still live
                        active_conditions.add(pending_result.condition_id)
                max_concurrent = CONFIG.trading.max_concurrent_markets
                if len(active_conditions) >= max_concurrent:
                    logger.info(
                        "oeg_concurrent_cap_reached",
                        active=len(active_conditions),
                        cap=max_concurrent,
                        condition_id=signal.condition_id[:16],
                    )
                    continue

                logger.info(
                    "oeg_signal_received",
                    signal_id=signal.signal_id[:8],
                    question=signal.market_question[:50],
                    expected_profit=f"${signal.expected_profit:.4f}",
                    active_conditions=len(active_conditions),
                )

                # 动态添加 condition_id 到 FillTracker 订阅
                if self._fill_tracker:
                    self._fill_tracker.subscribe_condition(signal.condition_id)

                # 并发执行套利
                result = await self._execute_arbitrage(signal)

                # 初始结果回调 (用于风控快速判定)
                if self._result_callback:
                    await self._result_callback(result)

            except asyncio.CancelledError:
                logger.info("oeg_execution_loop_cancelled")
                break
            except Exception as e:
                logger.error("oeg_execution_error", error=str(e))
                await asyncio.sleep(0.5)

        # 清理
        await self._fill_tracker.stop()
        fill_tracker_task.cancel()

    # ============================================================
    # 并发下单核心
    # ============================================================

    async def _execute_arbitrage(self, signal: TradeSignal) -> ArbitrageResult:
        """
        并发执行套利的双腿订单
        
        使用 asyncio.gather 确保两腿同时发出
        """
        result = ArbitrageResult(
            signal_id=signal.signal_id,
            condition_id=signal.condition_id,
        )

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # ☁️ DRY RUN: 虚拟挂单 + 监控被动成交率
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if CONFIG.flags.dry_run:
            logger.info(
                "DRY_RUN_SIGNAL",
                signal_id=signal.signal_id[:8],
                question=signal.market_question[:50],
                vwap_yes=f"{signal.yes_price:.4f}",
                vwap_no=f"{signal.no_price:.4f}",
                size=signal.yes_size,
                expected_profit=f"${signal.expected_profit:.4f}",
                order_type=signal.order_type,
                note="virtual order placed (dry run)",
            )
            result.yes_result = ExecutionResult(
                signal_id=signal.signal_id,
                token_id=signal.yes_token_id,
                side=Side.YES,
                status=OrderStatus.CANCELLED,
            )
            result.no_result = ExecutionResult(
                signal_id=signal.signal_id,
                token_id=signal.no_token_id,
                side=Side.NO,
                status=OrderStatus.CANCELLED,
            )
            result.is_complete = True
            # ── 虚拟成交追踪: 记录挂单, 稍后检查是否会被吃 ──
            self._virtual_orders = getattr(self, '_virtual_orders', {})
            self._virtual_orders[signal.signal_id] = {
                "condition_id": signal.condition_id,
                "yes_token": signal.yes_token_id,
                "no_token": signal.no_token_id,
                "bid_yes": signal.yes_price,
                "bid_no": signal.no_price,
                "size": signal.yes_size,
                "placed_at": time.time(),
                "filled_yes": False,
                "filled_no": False,
                "adverse_selection": False,  # True if filled quickly = bad news
            }
            # 仍然回调 RMC 以记录到 trade_log (status=CANCELLED)
            if self._result_callback:
                await self._result_callback(result)
            return result

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # ⚡ 核心: 并发下单, 消除 Leg Risk ⚡
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        try:
            order_type = getattr(signal, 'order_type', 'GTC') or 'GTC'
            yes_task = asyncio.create_task(
                self._place_order(
                    token_id=signal.yes_token_id,
                    side="BUY",
                    price=signal.yes_price,
                    size=signal.yes_size,
                    signal_id=signal.signal_id,
                    condition_id=signal.condition_id,
                    order_side=Side.YES,
                    order_type=order_type,
                )
            )
            no_task = asyncio.create_task(
                self._place_order(
                    token_id=signal.no_token_id,
                    side="BUY",
                    price=signal.no_price,
                    size=signal.no_size,
                    signal_id=signal.signal_id,
                    condition_id=signal.condition_id,
                    order_side=Side.NO,
                    order_type=order_type,
                )
            )

            yes_result, no_result = await asyncio.gather(
                yes_task, no_task, return_exceptions=True
            )

            # 处理异常
            if isinstance(yes_result, Exception):
                yes_result = ExecutionResult(
                    signal_id=signal.signal_id,
                    token_id=signal.yes_token_id,
                    side=Side.YES,
                    status=OrderStatus.FAILED,
                    error_message=str(yes_result),
                )
            if isinstance(no_result, Exception):
                no_result = ExecutionResult(
                    signal_id=signal.signal_id,
                    token_id=signal.no_token_id,
                    side=Side.NO,
                    status=OrderStatus.FAILED,
                    error_message=str(no_result),
                )

        except Exception as e:
            logger.error("gather_execution_error", error=str(e))
            yes_result = ExecutionResult(
                signal_id=signal.signal_id,
                token_id=signal.yes_token_id,
                side=Side.YES,
                status=OrderStatus.FAILED,
                error_message=str(e),
            )
            no_result = ExecutionResult(
                signal_id=signal.signal_id,
                token_id=signal.no_token_id,
                side=Side.NO,
                status=OrderStatus.FAILED,
                error_message=str(e),
            )

        result.yes_result = yes_result
        result.no_result = no_result
        result.is_complete = True

        # 注册到 pending 表, 等待 WS 撮合回执更新
        self._pending[signal.signal_id] = result
        
        # ── 淡出机制: 记录 Maker 订单放置时间 ──
        if order_type == "GTX" and not CONFIG.flags.dry_run:
            self._maker_order_times = getattr(self, '_maker_order_times', {})
            self._maker_order_times[signal.signal_id] = time.time()
            logger.debug("maker_order_placed_at", signal_id=signal.signal_id[:8])

        # 向 FillTracker 注册追踪
        if self._fill_tracker:
            if yes_result.order_id:
                self._fill_tracker.track_order(
                    order_id=yes_result.order_id,
                    signal_id=signal.signal_id,
                    token_id=signal.yes_token_id,
                    side=Side.YES,
                    expected_size=signal.yes_size,
                    expected_price=signal.yes_price,
                    condition_id=signal.condition_id,
                )
            if no_result.order_id:
                self._fill_tracker.track_order(
                    order_id=no_result.order_id,
                    signal_id=signal.signal_id,
                    token_id=signal.no_token_id,
                    side=Side.NO,
                    expected_size=signal.no_size,
                    expected_price=signal.no_price,
                    condition_id=signal.condition_id,
                )

        # 检测单边敞口风险
        if result.has_leg_risk:
            self._stats["leg_risk_count"] += 1
            logger.critical(
                "OEG_LEG_RISK_DETECTED",
                signal_id=signal.signal_id[:8],
                condition_id=signal.condition_id[:16],
            )
            if self._circuit_breaker_callback:
                self._circuit_breaker_callback(signal.condition_id)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 📨 Telegram 通知: Maker 信号执行结果 (限频5min/condition)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        self._stats.setdefault("maker_signals_today", 0)
        self._stats["maker_signals_today"] += 1
        if signal.signal_type.name == "MAKER_ARB":
            cid = signal.condition_id[:16]
            now = time.time()
            self._maker_tg_last = getattr(self, '_maker_tg_last', {})
            if now - self._maker_tg_last.get(cid, 0) > 300:
                self._maker_tg_last[cid] = now
                try:
                    from core.telegram_notify import send_message, build_maker_signal_message
                    from core.config import CONFIG as _CFG
                    tg = _CFG.telegram
                    if tg.enabled and tg.bot_token and tg.chat_id:
                        msg = build_maker_signal_message({
                            "question": signal.market_question[:50],
                            "bid_sum": signal.yes_price + signal.no_price,
                            "our_bid_yes": signal.yes_price,
                            "our_bid_no": signal.no_price,
                            "profit_per_share": 1.0 - (signal.yes_price + signal.no_price),
                            "total_profit": signal.expected_profit,
                            "size": signal.yes_size,
                            "order_status": f"YES={yes_result.status.name} NO={no_result.status.name}",
                        })
                        await send_message(tg.bot_token, tg.chat_id, msg)
                        logger.info("oeg_maker_signal_telegram_sent")
                except Exception as e:
                    logger.warning("oeg_maker_telegram_error: %s", e)

        return result

    async def _place_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        signal_id: str,
        condition_id: str,
        order_side: Side,
        order_type: str = "GTC",
    ) -> ExecutionResult:
        """通过 py-clob-client 创建并发送订单"""
        result = ExecutionResult(
            signal_id=signal_id,
            token_id=token_id,
            side=order_side,
        )

        start_ts = time.time()

        try:
            client = self._get_client()

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # 使用 py-clob-client SDK 下单
            # 内部自动处理 EIP-712 签名
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            from py_clob_client_v2.clob_types import OrderArgs, OrderType as ClobOrderType

            # v1.4: support GTX (Maker-Only) via post_only=True
            # Polymarket SDK has no OrderType.GTX; Maker orders = GTC + post_only=True
            post_only = order_type == "GTX"
            clob_order_type = ClobOrderType.GTC  # always GTC; maker via post_only flag

            logger.info(
                "oeg_placing_order",
                signal_id=signal_id[:8],
                side=order_side.value,
                order_type=order_type,
                post_only=post_only,
                price=price,
                size=size,
                token_id=token_id[:16],
            )

            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=side,
            )

            signed_order = await asyncio.to_thread(client.create_order, order_args)
            response = await asyncio.to_thread(
                client.post_order, signed_order, clob_order_type, post_only
            )

            elapsed_ms = (time.time() - start_ts) * 1000

            # 解析响应
            if response and isinstance(response, dict):
                order_id = response.get("orderID", response.get("order_id", ""))
                status_str = response.get("status", "").lower()

                result.order_id = str(order_id)
                result.status = OrderStatus.SUBMITTED
                result.filled_size = size  # 预估, 等待 WS 撮合回执
                result.avg_fill_price = price

                self._stats["orders_sent"] += 1

                logger.info(
                    "oeg_order_submitted",
                    signal_id=signal_id[:8],
                    side=order_side.value,
                    order_id=str(order_id)[:16],
                    elapsed_ms=f"{elapsed_ms:.1f}",
                )
            else:
                result.status = OrderStatus.FAILED
                result.error_message = f"Unexpected response: {str(response)[:200]}"
                self._stats["orders_failed"] += 1

                logger.error(
                    "oeg_order_failed",
                    signal_id=signal_id[:8],
                    response=str(response)[:200],
                )

        except Exception as e:
            result.status = OrderStatus.FAILED
            result.error_message = str(e)
            self._stats["orders_failed"] += 1

            logger.error(
                "oeg_order_exception",
                signal_id=signal_id[:8],
                side=order_side.value,
                error=str(e),
            )

        return result

    # ============================================================
    # 风控接口
    # ============================================================

    def disable_market(self, condition_id: str) -> None:
        """由 RMC 调用: 禁用某个市场的交易"""
        self._disabled_markets.add(condition_id)
        logger.warning("oeg_market_disabled", condition_id=condition_id[:16])

    def enable_market(self, condition_id: str) -> None:
        """由 RMC 调用: 恢复某个市场的交易"""
        self._disabled_markets.discard(condition_id)
        logger.info("oeg_market_enabled", condition_id=condition_id[:16])

    def get_stats(self) -> dict:
        """获取执行统计"""
        return self._stats.copy()

    # ============================================================
    # 虚拟成交追踪 (DRY_RUN 模式专用)
    # ============================================================
    async def _virtual_fill_tracker_loop(self) -> None:
        """
        DRY_RUN 模式下, 追踪虚拟挂单是否会被真实盘口吃掉。
        
        逻辑: 每 10 秒拉取虚拟订单对应 token 的订单簿, 检查:
        - 如果 ask 价格降到 ≤ 我们的 bid, 说明我们的挂单会被吃 (FILLED)
        - 如果在 5 秒内就被吃, 标记 adverse_selection (逆向选择风险)
        - 如果 5 分钟内都没被吃, 虚拟订单过期
        """
        client = self._get_client()
        while True:
            try:
                await asyncio.sleep(10)  # check every 10s
                now = time.time()
                expired = []
                active_count = len(self._virtual_orders)
                if active_count > 0:
                    logger.info("virtual_fill_tracker_check", active=active_count)
                
                for sig_id, vo in list(self._virtual_orders.items()):
                    age = now - vo["placed_at"]
                    
                    # 淡出机制: 超过 stale_seconds 仍双未成交 → 虚拟撤单
                    if age > self._maker_stale_seconds and not vo["filled_yes"] and not vo["filled_no"]:
                        logger.info(
                            "virtual_stale_cancel",
                            signal_id=sig_id[:8],
                            age=f"{age:.0f}s",
                            note="virtual stale order auto-cancelled (fade defense)",
                        )
                        self._stats.setdefault("virtual_stale_cancels", 0)
                        self._stats["virtual_stale_cancels"] += 1
                        expired.append(sig_id)
                        continue
                    
                    # 最终过期: 5 分钟 → 移除
                    if age > 300:
                        logger.info(
                            "virtual_order_expired_unfilled",
                            signal_id=sig_id[:8],
                            age=f"{age:.0f}s",
                            filled_yes=vo["filled_yes"],
                            filled_no=vo["filled_no"],
                            note="no adverse selection - safe to place",
                        )
                        expired.append(sig_id)
                        continue
                    
                    # 检查 YES 腿: ask 是否降到我们的 bid
                    if not vo["filled_yes"]:
                        try:
                            book = await asyncio.to_thread(client.get_order_book, vo["yes_token"])
                            best_ask = None
                            if isinstance(book, dict):
                                asks = book.get("asks", [])
                                if asks and isinstance(asks[0], dict):
                                    best_ask = float(asks[0]["price"])
                            if best_ask is not None and best_ask <= vo["bid_yes"]:
                                vo["filled_yes"] = True
                                fill_time = now - vo["placed_at"]
                                vo["adverse_selection"] = fill_time < 5.0
                                logger.info(
                                    "virtual_fill_YES",
                                    signal_id=sig_id[:8],
                                    bid_yes=vo["bid_yes"],
                                    ask_now=best_ask,
                                    fill_time=f"{fill_time:.1f}s",
                                    adverse=vo["adverse_selection"],
                                )
                        except Exception:
                            pass
                    
                    # 检查 NO 腿
                    if not vo["filled_no"]:
                        try:
                            book = await asyncio.to_thread(client.get_order_book, vo["no_token"])
                            best_ask = None
                            if isinstance(book, dict):
                                asks = book.get("asks", [])
                                if asks and isinstance(asks[0], dict):
                                    best_ask = float(asks[0]["price"])
                            if best_ask is not None and best_ask <= vo["bid_no"]:
                                vo["filled_no"] = True
                                fill_time = now - vo["placed_at"]
                                if fill_time < 5.0:
                                    vo["adverse_selection"] = True
                                logger.info(
                                    "virtual_fill_NO",
                                    signal_id=sig_id[:8],
                                    bid_no=vo["bid_no"],
                                    ask_now=best_ask,
                                    fill_time=f"{fill_time:.1f}s",
                                    adverse=fill_time < 5.0,
                                )
                        except Exception:
                            pass
                    
                    # 双腿都成交 → 记录结果
                    if vo["filled_yes"] and vo["filled_no"]:
                        profit = (1.0 - vo["bid_yes"] - vo["bid_no"]) * vo["size"]
                        logger.info(
                            "virtual_fill_COMPLETE",
                            signal_id=sig_id[:8],
                            profit=f"${profit:.4f}",
                            adverse_selection=vo["adverse_selection"],
                            age=f"{now - vo['placed_at']:.1f}s",
                        )
                        self._stats.setdefault("virtual_fills", 0)
                        self._stats["virtual_fills"] += 1
                        if vo["adverse_selection"]:
                            self._stats.setdefault("virtual_adverse_selections", 0)
                            self._stats["virtual_adverse_selections"] += 1
                        # Persist to SQLite for weekend analysis
                        try:
                            import sqlite3 as _sq
                            from pathlib import Path as _P
                            _db = str(_P(__file__).resolve().parent.parent / "db" / "arbitrage.db")
                            _c = _sq.connect(_db)
                            _c.execute("""CREATE TABLE IF NOT EXISTS virtual_fills (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                signal_id TEXT, condition_id TEXT,
                                bid_yes REAL, bid_no REAL, size REAL,
                                fill_time_ms REAL, adverse_selection INTEGER,
                                profit REAL, created_at TEXT DEFAULT (datetime('now')))""")
                            _c.execute("INSERT INTO virtual_fills (signal_id,condition_id,bid_yes,bid_no,size,fill_time_ms,adverse_selection,profit) VALUES (?,?,?,?,?,?,?,?)",
                                (sig_id, vo.get("condition_id",""), vo["bid_yes"], vo["bid_no"], vo["size"],
                                 (now - vo["placed_at"]) * 1000, 1 if vo["adverse_selection"] else 0, profit))
                            _c.commit()
                            _c.close()
                        except Exception as _dbe:
                            logger.debug("virtual_fill_db_error: %s", _dbe)
                        expired.append(sig_id)
                
                # 统计
                maker_stale = self._stats.get("virtual_stale_cancels", 0)
                vf = self._stats.get("virtual_fills", 0)
                va = self._stats.get("virtual_adverse_selections", 0)
                logger.info(
                    "virtual_tracker_status",
                    active=len(self._virtual_orders),
                    total_fills=vf,
                    adverse=va,
                    stale_cancels=maker_stale,
                )
                # 清除过期/完成的订单
                for sig_id in expired:
                    self._virtual_orders.pop(sig_id, None)
                    
                # 日志汇总
                active = len(self._virtual_orders)
                if active > 0:
                    self._stats.setdefault("virtual_orders_active", 0)
                    self._stats["virtual_orders_active"] = active
                    
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("virtual_fill_tracker_error: %s", e)
                await asyncio.sleep(30)

    # ============================================================
    # 淡出机制: 自动撤回超时 Maker 订单 (Adverse Selection Defense)
    # ============================================================
    async def _maker_stale_sweeper_loop(self) -> None:
        """
        实盘保护: 自动撤回存活超过 MAKER_STALE_SECONDS 的 Maker 订单。
        
        原理: 如果订单挂上 30 秒还没被成交, 说明市场冷清。
        在冷清的市场中, 突发新闻砸盘的杀伤力最大 (Stale Quotes 被狙击)。
        及时撤回未成交流动性 = 降低逆向选择风险。
        """
        client = self._get_client()
        while True:
            try:
                await asyncio.sleep(10)
                now = time.time()
                stale_ids = []
                
                self._maker_order_times = getattr(self, '_maker_order_times', {})
                for sig_id, placed_at in list(self._maker_order_times.items()):
                    age = now - placed_at
                    if age > self._maker_stale_seconds:
                        stale_ids.append(sig_id)
                
                if not stale_ids:
                    continue
                
                # Cancel stale orders
                from py_clob_client_v2.clob_types import OrderPayload
                for sig_id in stale_ids:
                    result = self._pending.get(sig_id)
                    if not result or result.is_complete:
                        self._maker_order_times.pop(sig_id, None)
                        continue
                    
                    # Cancel both legs
                    for leg in [result.yes_result, result.no_result]:
                        if leg.order_id and leg.status == OrderStatus.SUBMITTED:
                            try:
                                payload = OrderPayload(orderID=leg.order_id)
                                await asyncio.to_thread(client.cancel_order, payload)
                                logger.info(
                                    "maker_stale_cancel",
                                    signal_id=sig_id[:8],
                                    order_id=leg.order_id[:16],
                                    age=f"{age:.0f}s",
                                    note="stale order auto-cancelled (fade defense)",
                                )
                            except Exception as e:
                                logger.warning("maker_stale_cancel_error: %s", e)
                    
                    self._maker_order_times.pop(sig_id, None)
                    self._stats.setdefault("maker_stale_cancels", 0)
                    self._stats["maker_stale_cancels"] += 1
                    
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("maker_stale_sweeper_error: %s", e)
                await asyncio.sleep(30)
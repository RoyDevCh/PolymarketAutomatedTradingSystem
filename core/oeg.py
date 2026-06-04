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
    ):
        self.cfg = CONFIG.clob
        self.trading_cfg = CONFIG.trading

        # 回调函数
        self._result_callback = result_callback
        self._circuit_breaker_callback = circuit_breaker_callback

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
        """FillTracker 回调: 交易链上确认"""
        self._stats["orders_confirmed"] += 1
        logger.info(
            "oeg_trade_confirmed_ws",
            signal_id=tracker.signal_id[:8],
            order_id=tracker.order_id[:16],
            side=tracker.side.value,
            size=tracker.confirmed_size,
            price=tracker.confirmed_price,
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

                logger.info(
                    "oeg_signal_received",
                    signal_id=signal.signal_id[:8],
                    question=signal.market_question[:50],
                    expected_profit=f"${signal.expected_profit:.4f}",
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
        # ⚡ 核心: 并发下单, 消除 Leg Risk ⚡
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        try:
            yes_task = asyncio.create_task(
                self._place_order(
                    token_id=signal.yes_token_id,
                    side="BUY",
                    price=signal.yes_price,
                    size=signal.yes_size,
                    signal_id=signal.signal_id,
                    condition_id=signal.condition_id,
                    order_side=Side.YES,
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

            logger.debug(
                "oeg_placing_order",
                signal_id=signal_id[:8],
                side=order_side.value,
                price=price,
                size=size,
                token_id=token_id[:16],
            )

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # 使用 py-clob-client SDK 下单
            # 内部自动处理 EIP-712 签名
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            from py_clob_client.clob_types import OrderArgs

            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=side,
            )

            signed_order = client.create_order(order_args)
            response = client.post_order(signed_order, OrderType.GTC)

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
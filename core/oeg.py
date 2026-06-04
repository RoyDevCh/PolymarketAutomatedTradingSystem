"""
Polymarket 自动套利系统 - 订单执行网关 (OEG)

职责:
1. 从信号队列消费 TradeSignal
2. 构造 JSON Payload + EIP-712 签名
3. asyncio.gather 并发下发 YES/NO 双腿订单, 消除 Leg Risk
4. 监听私有 WebSocket 撮合回执
5. 向 RMC 报告执行结果
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

import aiohttp
import structlog

from core.config import CONFIG
from core.clob_client import get_clob_client
from core.models import (
    ArbitrageResult,
    ExecutionResult,
    OrderRequest,
    OrderStatus,
    OrderType,
    Side,
    TradeSignal,
)

logger = structlog.get_logger(__name__)


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
    """

    def __init__(
        self,
        result_callback,  # Callable[[ArbitrageResult], None]
        circuit_breaker_callback,  # Callable[[str], None]  -> condition_id
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

        # 执行统计
        self._stats = {
            "signals_received": 0,
            "orders_sent": 0,
            "orders_matched": 0,
            "orders_failed": 0,
            "leg_risk_count": 0,
        }

    def _get_client(self):
        """惰性获取 CLOB Client"""
        if self._client is None:
            self._client = get_clob_client()
        return self._client

    # ================================================================
    # 主执行循环
    # ================================================================

    async def execution_loop(self, signal_queue: asyncio.Queue) -> None:
        """
        后台任务: 从信号队列持续消费并执行
        
        这是 OEG 的主入口:
        1. 从 queue 获取 TradeSignal
        2. 检查风控状态 (市场是否已被禁用)
        3. 并发下单
        4. 回调结果给 RMC
        """
        logger.info("oeg_execution_loop_started")

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

                # 并发执行套利
                result = await self._execute_arbitrage(signal)

                # 回调 RMC
                if self._result_callback:
                    self._result_callback(result)

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

            except asyncio.CancelledError:
                logger.info("oeg_execution_loop_cancelled")
                break
            except Exception as e:
                logger.error("oeg_execution_error", error=str(e))
                await asyncio.sleep(0.5)

    # ================================================================
    # 并发下单核心
    # ================================================================

    async def _execute_arbitrage(self, signal: TradeSignal) -> ArbitrageResult:
        """
        并发执行套利的双腿订单
        
        使用 asyncio.gather 确保两腿同时发出:
        - 如果任一腿抛出异常, 不影响另一腿
        - 两腿结果汇总为 ArbitrageResult
        """
        result = ArbitrageResult(
            signal_id=signal.signal_id,
            condition_id=signal.condition_id,
        )

        # 构造 YES 和 NO 订单请求
        yes_request = OrderRequest(
            token_id=signal.yes_token_id,
            side=Side.YES,
            price=signal.yes_price,
            size=signal.yes_size,
            order_type=OrderType.GTC,
            signal_id=signal.signal_id,
        )

        no_request = OrderRequest(
            token_id=signal.no_token_id,
            side=Side.NO,
            price=signal.no_price,
            size=signal.no_size,
            order_type=OrderType.GTC,
            signal_id=signal.signal_id,
        )

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # ⚡ 核心: 并发下单, 消除 Leg Risk ⚡
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        try:
            yes_result, no_result = await asyncio.gather(
                self._place_order(yes_request),
                self._place_order(no_request),
                return_exceptions=False,  # 任一失败则整体失败, 触发异常处理
            )
        except Exception as e:
            # 一腿失败的情况: 需要逐个尝试
            logger.error("gather_execution_error", error=str(e))
            yes_task = asyncio.create_task(self._place_order(yes_request))
            no_task = asyncio.create_task(self._place_order(no_request))

            yes_result = await self._safe_await(yes_task)
            no_result = await self._safe_await(no_task)

        result.yes_result = yes_result
        result.no_result = no_result
        result.is_complete = True

        # 计算实际盈亏
        if yes_result.status == OrderStatus.MATCHED and no_result.status == OrderStatus.MATCHED:
            total_filled_cost = (
                yes_result.avg_fill_price * yes_result.filled_size
                + no_result.avg_fill_price * no_result.filled_size
            )
            total_payout = min(yes_result.filled_size, no_result.filled_size)
            result.realized_profit = total_payout - total_filled_cost
        elif yes_result.status == OrderStatus.MATCHED or no_result.status == OrderStatus.MATCHED:
            # 单边成交 - 需要风控介入
            result.realized_profit = 0.0

        return result

    async def _place_order(self, request: OrderRequest) -> ExecutionResult:
        """
        下单单腿订单
        
        使用 py-clob-client 构造并签名订单:
        1. 构造 JSON Payload
        2. EIP-712 签名 (由 py-clob-client 内部处理)
        3. HTTP POST 至 CLOB API
        """
        result = ExecutionResult(
            signal_id=request.signal_id,
            token_id=request.token_id,
            side=request.side,
        )

        start_ts = time.time()

        try:
            client = self._get_client()

            # 使用 py-clob-client 创建并发送订单
            # Side 映射: YES -> BUY yes_token, NO -> BUY no_token
            # 两者都是 BUY 操作 (套利策略: 同时买入 YES 和 NO)
            clob_side = "BUY"

            # 构造订单
            order_payload = {
                "token_id": request.token_id,
                "price": request.price,
                "size": request.size,
                "side": clob_side,
                "type": request.order_type.value,
            }

            logger.debug(
                "oeg_placing_order",
                signal_id=request.signal_id[:8],
                side=request.side.value,
                price=request.price,
                size=request.size,
                token_id=request.token_id[:16],
            )

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # 通过 py-clob-client SDK 下单
            # 内部自动处理 EIP-712 签名
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            response = client.create_and_post_order(
                token_id=request.token_id,
                price=request.price,
                size=request.size,
                side="BUY",
                order_type=request.order_type.value,
            )

            elapsed_ms = (time.time() - start_ts) * 1000

            # 解析响应
            if response and isinstance(response, dict):
                order_id = response.get("orderID", response.get("order_id", ""))
                status_str = response.get("status", "").lower()

                result.order_id = order_id
                result.status = OrderStatus.SUBMITTED
                result.filled_size = request.size  # 预估值, 等撮合回执更新
                result.avg_fill_price = request.price

                self._stats["orders_sent"] += 1

                logger.info(
                    "oeg_order_submitted",
                    signal_id=request.signal_id[:8],
                    side=request.side.value,
                    order_id=order_id[:16] if order_id else "N/A",
                    elapsed_ms=f"{elapsed_ms:.1f}",
                )
            else:
                result.status = OrderStatus.FAILED
                result.error_message = f"Unexpected response: {str(response)[:200]}"
                self._stats["orders_failed"] += 1

                logger.error(
                    "oeg_order_failed",
                    signal_id=request.signal_id[:8],
                    response=str(response)[:200],
                )

        except Exception as e:
            result.status = OrderStatus.FAILED
            result.error_message = str(e)
            self._stats["orders_failed"] += 1

            logger.error(
                "oeg_order_exception",
                signal_id=request.signal_id[:8],
                side=request.side.value,
                error=str(e),
            )

        return result

    @staticmethod
    async def _safe_await(task: asyncio.Task) -> ExecutionResult:
        """安全等待异步任务, 捕获异常"""
        try:
            return await task
        except Exception as e:
            return ExecutionResult(
                signal_id="",
                token_id="",
                side=Side.YES,
                status=OrderStatus.FAILED,
                error_message=str(e),
            )

    # ================================================================
    # 撮合回执监听 (Phase 3)
    # ================================================================

    async def _listen_fill_updates(self) -> None:
        """
        监听私有 WebSocket 频道, 接收订单撮合回执
        
        流程:
        1. 建立 WebSocket 连接 (需认证)
        2. 监听 order_fill 事件
        3. 更新 pending 中的订单状态
        4. 匹配 signal_id, 触发 RMC 回调
        """
        # 此功能在 Phase 3 实现, 当前先使用轮询方式检查
        logger.info("fill_listener_placeholder_active")
        # TODO: 实现 WebSocket 私有频道监听

    async def check_order_status(self, order_id: str) -> OrderStatus:
        """查询订单状态 (轮询备用方案)"""
        try:
            client = self._get_client()
            order = client.get_order(order_id)
            if order:
                status_str = order.get("status", "").lower()
                if status_str == "live":
                    return OrderStatus.SUBMITTED
                elif status_str == "matched":
                    return OrderStatus.MATCHED
                elif status_str == "cancelled":
                    return OrderStatus.CANCELLED
            return OrderStatus.PENDING
        except Exception as e:
            logger.error("order_status_check_failed", order_id=order_id[:16], error=str(e))
            return OrderStatus.PENDING

    # ================================================================
    # 风控接口
    # ================================================================

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
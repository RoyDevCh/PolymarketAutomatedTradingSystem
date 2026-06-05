"""Hourly Telegram heartbeat background task."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from core.config import CONFIG
from core.telegram_notify import build_heartbeat_message, send_message, telegram_configured

logger = logging.getLogger(__name__)

StatsProvider = Callable[[], Awaitable[dict[str, Any]]]


def _format_uptime(started_at: float) -> str:
    secs = max(0, int(time.time() - started_at))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"


async def telegram_heartbeat_loop(
    get_stats: StatsProvider,
    *,
    started_at: float,
    interval_seconds: int | None = None,
) -> None:
    tg = CONFIG.telegram
    interval = interval_seconds or tg.heartbeat_interval_seconds
    if not telegram_configured(tg.bot_token, tg.chat_id, tg.enabled):
        logger.info("Telegram heartbeat disabled (not configured)")
        return

    logger.info("Telegram heartbeat started interval=%ss", interval)

    async def _send_once() -> None:
        stats = await get_stats()
        stats.setdefault("uptime_human", _format_uptime(started_at))
        msg = build_heartbeat_message(stats)
        ok = await send_message(tg.bot_token, tg.chat_id, msg)
        if ok:
            logger.info("Telegram heartbeat sent")
        else:
            logger.warning("Telegram heartbeat send failed")

    try:
        await _send_once()
    except Exception:
        logger.exception("Telegram startup heartbeat error")

    while True:
        try:
            await asyncio.sleep(interval)
            await _send_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram heartbeat loop error")

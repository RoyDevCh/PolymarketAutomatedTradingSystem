"""Telegram notifications (Phase 4+).

v1.5: Fix CancelledError — use httpx sync in thread executor instead of
      aiohttp (which can be cancelled by the main event loop's task churn).
      Added build_maker_signal_message for Maker arbitrage alerts.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _proxy_url() -> str | None:
    return os.environ.get("https_proxy") or os.environ.get("http_proxy") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")


def telegram_configured(bot_token: str, chat_id: str, enabled: bool) -> bool:
    if not enabled:
        return False
    return bool(bot_token and chat_id)


async def send_message(bot_token: str, chat_id: str, text: str) -> bool:
    """Send Telegram message using httpx sync in thread executor.

    Uses asyncio.to_thread + httpx.sync to avoid CancelledError that occurs
    when aiohttp's TLS handshake is cancelled by the busy main event loop.
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    proxy = _proxy_url()

    import asyncio

    def _sync_send() -> bool:
        try:
            with httpx.Client(proxy=proxy, timeout=httpx.Timeout(15.0), follow_redirects=True) as client:
                resp = client.post(url, json=payload)
                if resp.status_code != 200:
                    logger.warning("Telegram send failed status=%s body=%s", resp.status_code, resp.text[:300])
                    return False
                return True
        except Exception as e:
            logger.warning("Telegram _sync_send error: %s", e)
            return False

    try:
        return await asyncio.to_thread(_sync_send)
    except Exception:
        logger.exception("Telegram send_message outer error")
        return False


def build_heartbeat_message(stats: dict[str, Any]) -> str:
    mode = stats.get("mode", "taker+maker")
    lines = [
        "🤖 Polymarket Arb heartbeat",
        f"Uptime: {stats.get('uptime_human', 'n/a')}",
        f"Mode: {mode}",
        f"CLOB balance: {stats.get('clob_balance', 'n/a')}",
        f"Trades today: {stats.get('trades_today', 'n/a')}",
        f"Last signal: {stats.get('last_signal_time', 'n/a')}",
        f"Markets monitored: {stats.get('markets_monitored', 'n/a')}",
    ]
    maker_signals = stats.get("maker_signals_today", 0)
    if maker_signals:
        lines.append(f"Maker signals today: {maker_signals}")
    oeg = stats.get("oeg")
    rmc = stats.get("rmc")
    if oeg:
        lines.append(f"OEG: {oeg}")
    if rmc:
        lines.append(f"RMC: {rmc}")
    return "\n".join(lines)


def build_maker_signal_message(signal_info: dict[str, Any]) -> str:
    """Build message for a Maker arbitrage signal detected."""
    lines = [
        "💡 Maker Arb Signal",
        f"Market: {signal_info.get('question', 'n/a')[:50]}",
        f"Bid sum: {signal_info.get('bid_sum', 0):.4f}",
        f"Our bids: YES={signal_info.get('our_bid_yes', 0):.2f} NO={signal_info.get('our_bid_no', 0):.2f}",
        f"Profit/share: {signal_info.get('profit_per_share', 0):.4f}",
        f"Total profit est: ${signal_info.get('total_profit', 0):.4f}",
        f"Size: {signal_info.get('size', 0):.1f} shares",
    ]
    status = signal_info.get("order_status", "")
    if status:
        lines.append(f"Order: {status}")
    return "\n".join(lines)


def build_phase3_pass_message(evaluation: Any) -> str:
    """Build one-shot Phase 3 PASS Telegram message."""
    lines = [
        "✅ Phase 3 PASS",
        "Polymarket Arb Go/No-Go criteria met.",
        "",
        f"Uptime: {evaluation.uptime_hours:.1f}h",
        f"Dual-leg attempts: {evaluation.dual_leg_attempts}",
        f"Ghost pending: {evaluation.ghost_pending}",
        f"Leg risk: {evaluation.leg_risk_count} ({evaluation.leg_risk_rate:.1%})",
        f"Slippage pass rate: {evaluation.slippage_pass_rate:.1%} ({evaluation.slippage_samples} samples)",
        f"Net PnL: ${evaluation.net_pnl:.4f}",
        "",
        "Ready for Phase 4: increase MAX_TRADE_SIZE gradually.",
    ]
    return "\n".join(lines)
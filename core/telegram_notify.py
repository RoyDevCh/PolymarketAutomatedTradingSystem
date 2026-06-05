"""Telegram notifications (Phase 4)."""

from __future__ import annotations

import logging
import os
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


def _proxy_url() -> str | None:
    return os.environ.get("https_proxy") or os.environ.get("http_proxy") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")


def telegram_configured(bot_token: str, chat_id: str, enabled: bool) -> bool:
    if not enabled:
        return False
    return bool(bot_token and chat_id)


async def send_message(bot_token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    proxy = _proxy_url()
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.post(url, json=payload, proxy=proxy) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning("Telegram send failed status=%s body=%s", resp.status, body[:500])
                    return False
                return True
    except Exception:
        logger.exception("Telegram send_message error")
        return False


def build_heartbeat_message(stats: dict[str, Any]) -> str:
    lines = [
        "Polymarket Arb heartbeat",
        f"Uptime: {stats.get('uptime_human', 'n/a')}",
        f"CLOB balance: {stats.get('clob_balance', 'n/a')}",
        f"Trades today: {stats.get('trades_today', 'n/a')}",
        f"Last signal: {stats.get('last_signal_time', 'n/a')}",
        f"Markets monitored: {stats.get('markets_monitored', 'n/a')}",
    ]
    oeg = stats.get("oeg")
    rmc = stats.get("rmc")
    if oeg:
        lines.append(f"OEG: {oeg}")
    if rmc:
        lines.append(f"RMC: {rmc}")
    return "\n".join(lines)


def build_phase3_pass_message(evaluation: Any) -> str:
    """Build one-shot Phase 3 PASS Telegram message."""
    lines = [
        "Phase 3 PASS",
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

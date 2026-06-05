"""Background task: notify via Telegram once when Phase 3 Go/No-Go passes."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

import aiosqlite

from core.config import CONFIG
from core.phase3_evaluator import Phase3Evaluation, evaluate_phase3
from core.telegram_notify import build_phase3_pass_message, send_message, telegram_configured

logger = logging.getLogger(__name__)

DbProvider = Callable[[], Awaitable[Optional[aiosqlite.Connection]]]


def _flag_path() -> Path:
    return Path(CONFIG.db_path).parent / "phase3_notified.json"


def already_notified() -> bool:
    p = _flag_path()
    return p.exists()


def load_notification_record() -> dict | None:
    p = _flag_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def mark_notified(evaluation: Phase3Evaluation) -> None:
    p = _flag_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "notified_at": time.time(),
        "evaluation": evaluation.to_dict(),
    }
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("phase3_pass_recorded path=%s", p)


async def phase3_notify_loop(
    get_db: DbProvider,
    *,
    started_at: float,
    interval_seconds: int | None = None,
) -> None:
    """Periodically evaluate Phase 3; send one Telegram message on pass."""
    cfg = CONFIG.phase3
    tg = CONFIG.telegram
    interval = interval_seconds or cfg.check_interval_seconds

    if not cfg.enabled:
        logger.info("Phase 3 pass notification disabled")
        return

    if not telegram_configured(tg.bot_token, tg.chat_id, tg.enabled):
        logger.info("Phase 3 pass notification skipped (Telegram not configured)")
        return

    if already_notified():
        rec = load_notification_record()
        logger.info(
            "Phase 3 already notified at %s",
            rec.get("notified_at") if rec else "unknown",
        )
        return

    logger.info("Phase 3 pass watcher started interval=%ss", interval)

    while True:
        try:
            await asyncio.sleep(interval)
            db = await get_db()
            if not db:
                logger.warning("Phase 3 check skipped (db unavailable)")
                continue

            if already_notified():
                logger.info("Phase 3 pass already sent; watcher exiting")
                return

            evaluation = await evaluate_phase3(db, started_at=started_at)

            if evaluation.ready and not evaluation.passed:
                logger.info(
                    "Phase 3 in progress blockers=%s attempts=%s uptime=%.1fh pnl=%.4f",
                    evaluation.blockers,
                    evaluation.dual_leg_attempts,
                    evaluation.uptime_hours,
                    evaluation.net_pnl,
                )
            elif evaluation.passed:
                msg = build_phase3_pass_message(evaluation)
                ok = await send_message(tg.bot_token, tg.chat_id, msg)
                if ok:
                    mark_notified(evaluation)
                    logger.info("Phase 3 PASS notification sent")
                    return
                logger.warning("Phase 3 PASS notification send failed; will retry")
            else:
                logger.debug(
                    "Phase 3 not ready attempts=%s uptime=%.1fh",
                    evaluation.dual_leg_attempts,
                    evaluation.uptime_hours,
                )

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Phase 3 notify loop error")

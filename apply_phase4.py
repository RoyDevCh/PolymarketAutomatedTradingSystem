"""Apply Phase 4: telegram, systemd deploy helpers, main/rmc/config patches."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

TELEGRAM_NOTIFY = '''"""Telegram notifications (Phase 4)."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


def telegram_configured(bot_token: str, chat_id: str, enabled: bool) -> bool:
    if not enabled:
        return False
    return bool(bot_token and chat_id)


async def send_message(bot_token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as resp:
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
    return "\\n".join(lines)
'''

HEARTBEAT = '''"""Hourly Telegram heartbeat background task."""

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
    while True:
        try:
            await asyncio.sleep(interval)
            stats = await get_stats()
            stats.setdefault("uptime_human", _format_uptime(started_at))
            msg = build_heartbeat_message(stats)
            await send_message(tg.bot_token, tg.chat_id, msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram heartbeat loop error")
'''

SERVICE = """[Unit]
Description=Polymarket arbitrage trading bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=roy
WorkingDirectory=/home/roy/polymarket-arb
EnvironmentFile=-/home/roy/polymarket-arb/.env
Environment=HTTP_PROXY=http://127.0.0.1:7890
Environment=HTTPS_PROXY=http://127.0.0.1:7890
Environment=ALL_PROXY=socks5://127.0.0.1:7890
Environment=NO_PROXY=localhost,127.0.0.1,192.168.0.0/16
ExecStart=/home/roy/polymarket-arb/venv/bin/python /home/roy/polymarket-arb/main.py
Restart=always
RestartSec=10
KillSignal=SIGINT
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
"""

INSTALL_SH = """#!/usr/bin/env bash
set -euo pipefail
UNIT_NAME=polymarket-arb.service
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sudo cp "${SCRIPT_DIR}/polymarket-arb.service" "/etc/systemd/system/${UNIT_NAME}"
sudo systemctl daemon-reload
sudo systemctl enable "${UNIT_NAME}"
sudo systemctl restart "${UNIT_NAME}"
sudo systemctl --no-pager status "${UNIT_NAME}" || true
"""


def write_files() -> list[str]:
    report: list[str] = []
    (ROOT / "core" / "telegram_notify.py").write_text(TELEGRAM_NOTIFY, encoding="utf-8")
    report.append("core/telegram_notify.py")
    (ROOT / "core" / "heartbeat.py").write_text(HEARTBEAT, encoding="utf-8")
    report.append("core/heartbeat.py")
    deploy = ROOT / "deploy"
    deploy.mkdir(exist_ok=True)
    (deploy / "polymarket-arb.service").write_text(SERVICE, encoding="utf-8")
    (deploy / "install_systemd.sh").write_text(INSTALL_SH, encoding="utf-8", newline="\n")
    report.append("deploy/polymarket-arb.service")
    report.append("deploy/install_systemd.sh")
    return report


def patch_config() -> str:
    path = ROOT / "core" / "config.py"
    text = path.read_text(encoding="utf-8")
    if "heartbeat_interval_seconds" in text:
        return "config unchanged"
    needle = 'chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")'
    if needle not in text:
        return "config needle missing"
    repl = (
        needle
        + '\n    enabled: bool = os.getenv("TELEGRAM_ENABLED", "false").lower() in ("1", "true", "yes")'
        + '\n    heartbeat_interval_seconds: int = int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "3600"))'
    )
    path.write_text(text.replace(needle, repl, 1), encoding="utf-8")
    return "config patched"


def patch_rmc() -> str:
    path = ROOT / "core" / "rmc.py"
    text = path.read_text(encoding="utf-8")
    if "_last_signal_time" not in text:
        # after class init - find __init__ end self._signal_meta
        if "self._last_signal_time" not in text:
            text = text.replace(
                "self._signal_meta: dict[str, dict] = {}",
                "self._signal_meta: dict[str, dict] = {}\n        self._last_signal_time: float | None = None",
                1,
            )
    if "self._last_signal_time = time.time()" not in text:
        old = '        self._signal_meta[signal.signal_id] = {'
        new = (
            "        import time\n\n        self._last_signal_time = time.time()\n"
            "        self._signal_meta[signal.signal_id] = {"
        )
        if old in text:
            text = text.replace(old, new, 1)
    if "def get_process_stats" not in text:
        text += '''

    def get_process_stats(self) -> dict:
        """Lightweight stats for Telegram heartbeat."""
        from datetime import datetime, timezone
        import time as _time

        out: dict = {"signal_meta_cache_size": len(self._signal_meta)}
        if self._last_signal_time:
            out["last_signal_time"] = datetime.fromtimestamp(
                self._last_signal_time, tz=timezone.utc
            ).isoformat()
        out["db_open"] = bool(self._db)
        return out
'''
    path.write_text(text, encoding="utf-8")
    return "rmc patched"


def patch_main() -> str:
    path = ROOT / "main.py"
    text = path.read_text(encoding="utf-8")
    if "telegram_heartbeat_loop" in text:
        return "main unchanged"

    if "from core.heartbeat import telegram_heartbeat_loop" not in text:
        text = text.replace(
            "from core.spe import StrategyPricingEngine\n",
            "from core.spe import StrategyPricingEngine\nfrom core.heartbeat import telegram_heartbeat_loop\n",
            1,
        )
    if "import time" not in text.split("class ArbitrageEngine")[0]:
        text = text.replace("import signal\n", "import signal\nimport time\n", 1)

    if "async def _collect_heartbeat_stats" not in text:
        insert = '''
    async def _collect_heartbeat_stats(self) -> dict:
        stats: dict = {
            "markets_monitored": len(getattr(self.spe, "_markets", {}) or {}),
            "oeg": self.oeg.get_stats(),
            "rmc": self.rmc.get_process_stats() if hasattr(self.rmc, "get_process_stats") else {},
        }
        rmc = stats.get("rmc") or {}
        if isinstance(rmc, dict) and rmc.get("last_signal_time"):
            stats["last_signal_time"] = rmc["last_signal_time"]
        if self.rmc._db:
            import time as _time
            from datetime import datetime, timezone

            day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            row = await self.rmc._db.execute_fetchone(
                "SELECT COUNT(*) AS n FROM trade_log WHERE timestamp >= ?",
                (day_start,),
            )
            if row:
                stats["trades_today"] = row[0] if not isinstance(row, dict) else row.get("n", row[0])
        try:
            client = self.oeg._client
            if client is None and hasattr(self.oeg, "_get_client"):
                client = await self.oeg._get_client() if asyncio.iscoroutinefunction(self.oeg._get_client) else self.oeg._get_client()
            if client and hasattr(client, "get_balance_allowance"):
                bal = client.get_balance_allowance()
                stats["clob_balance"] = str(bal)
        except Exception:
            stats.setdefault("clob_balance", "unavailable")
        return stats

'''
        anchor = "    async def start(self) -> None:"
        text = text.replace(anchor, insert + anchor, 1)

    if "name=\"telegram_heartbeat\"" not in text:
        old = """            asyncio.create_task(
                self.rmc.maintenance_loop(),
                name="rmc_maintenance",
            ),
        ]"""
        new = """            asyncio.create_task(
                self.rmc.maintenance_loop(),
                name="rmc_maintenance",
            ),
            asyncio.create_task(
                telegram_heartbeat_loop(
                    self._collect_heartbeat_stats,
                    started_at=self._started_at,
                ),
                name="telegram_heartbeat",
            ),
        ]"""
        if old not in text:
            return "main task block not found"
        text = text.replace(old, new, 1)

    if "self._started_at" not in text:
        text = text.replace(
            "        self._running = True\n\n        # ── 初始化数据库 ──",
            "        self._running = True\n        self._started_at = time.time()\n\n        # ── 初始化数据库 ──",
            1,
        )

    path.write_text(text, encoding="utf-8")
    return "main patched"


def patch_env_example() -> None:
    p = ROOT / ".env.example"
    block = (
        "\n# Phase 4 Telegram\nTELEGRAM_ENABLED=false\nTELEGRAM_BOT_TOKEN=\n"
        "TELEGRAM_CHAT_ID=\nHEARTBEAT_INTERVAL_SECONDS=3600\n"
    )
    if p.exists():
        t = p.read_text(encoding="utf-8")
        if "HEARTBEAT_INTERVAL_SECONDS" not in t:
            p.write_text(t.rstrip() + block, encoding="utf-8")
    else:
        p.write_text(block.lstrip(), encoding="utf-8")


def patch_requirements() -> None:
    p = ROOT / "requirements.txt"
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    for pkg in ("aiohttp", "paramiko"):
        if not any(l.strip().startswith(pkg) for l in lines):
            lines.append(pkg)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    rep = write_files()
    rep.append(patch_config())
    rep.append(patch_rmc())
    rep.append(patch_main())
    patch_env_example()
    patch_requirements()
    (ROOT / "phase4_apply_report.txt").write_text("\n".join(rep), encoding="utf-8")
    print("\n".join(rep))

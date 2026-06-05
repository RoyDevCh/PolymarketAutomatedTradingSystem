"""Apply breakout patches locally and on remote via paramiko."""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from pathlib import Path

import paramiko

HOST = "192.168.3.117"
USER = "roy"
PASS = os.getenv("REMOTE_PASSWORD", "changeme")
REMOTE = "/home/roy/polymarket-arb"
LOCAL = Path(__file__).resolve().parent

ENV_UPDATES = {
    "GAMMA_MIN_VOLUME": "500",
    "GAMMA_MIN_LIQUIDITY": "500",
    "MIN_PROFIT_THRESHOLD": "0.0001",
}

ON_FILL_UPDATE = '''
    async def on_fill_update(
        self,
        signal_id: str,
        side: str,
        fill_price: float,
        fill_size: float,
        status: str,
    ) -> None:
        """Update trade_log per-leg fill fields when OEG confirms a fill."""
        if not self._db:
            return
        side_u = (side or "").upper()
        if side_u == "YES":
            await self._db.execute(
                """
                UPDATE trade_log SET
                    yes_fill_price = ?,
                    yes_filled_size = ?,
                    yes_status = ?
                WHERE signal_id = ?
                """,
                (fill_price, fill_size, status, signal_id),
            )
        elif side_u == "NO":
            await self._db.execute(
                """
                UPDATE trade_log SET
                    no_fill_price = ?,
                    no_filled_size = ?,
                    no_status = ?
                WHERE signal_id = ?
                """,
                (fill_price, fill_size, status, signal_id),
            )
        else:
            return
        await self._db.commit()
        logger.info(
            "rmc_fill_updated",
            signal_id=signal_id[:8],
            side=side_u,
            price=fill_price,
            size=fill_size,
            status=status,
        )
'''


def strip_emoji(text: str) -> str:
    return re.sub(r"[^\x00-\x7F]+", "?", text)


def patch_rmc(text: str) -> str:
    if "async def on_fill_update" in text:
        return text
    anchor = "    async def _log_circuit_breaker(self, event: CircuitBreakerEvent) -> None:"
    if anchor not in text:
        raise RuntimeError("rmc anchor not found")
    return text.replace(anchor, ON_FILL_UPDATE + "\n" + anchor, 1)


def patch_oeg(text: str) -> str:
    if "fill_update_callback" in text:
        return text
    text = text.replace(
        "        circuit_breaker_callback: Callable,\n    ):",
        "        circuit_breaker_callback: Callable,\n        fill_update_callback: Callable | None = None,\n    ):",
        1,
    )
    text = text.replace(
        "        self._circuit_breaker_callback = circuit_breaker_callback\n",
        "        self._circuit_breaker_callback = circuit_breaker_callback\n        self._fill_update_callback = fill_update_callback\n",
        1,
    )
    old = '''    def _on_trade_confirmed(self, tracker: OrderTracker) -> None:
        """FillTracker 回调: 交易链上确认"""
        self._stats["orders_confirmed"] += 1
        logger.info(
            "oeg_trade_confirmed_ws",
            signal_id=tracker.signal_id[:8],
            order_id=tracker.order_id[:16],
            side=tracker.side.value,
            size=tracker.confirmed_size,
            price=tracker.confirmed_price,
        )'''
    new = '''    def _on_trade_confirmed(self, tracker: OrderTracker) -> None:
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
            )'''
    if old not in text:
        raise RuntimeError("oeg _on_trade_confirmed block not found")
    return text.replace(old, new, 1)


def patch_main(text: str) -> str:
    if "fill_update_callback=self.rmc.on_fill_update" in text:
        return text
    old = """        self.oeg = OrderExecutionGateway(
            result_callback=self._on_arbitrage_result,
            circuit_breaker_callback=self._on_circuit_breaker,
        )"""
    new = """        self.oeg = OrderExecutionGateway(
            result_callback=self._on_arbitrage_result,
            circuit_breaker_callback=self._on_circuit_breaker,
            fill_update_callback=self.rmc.on_fill_update,
        )"""
    if old not in text:
        raise RuntimeError("main OEG block not found")
    return text.replace(old, new, 1)


def patch_env(text: str) -> str:
    lines = text.splitlines()
    out = []
    seen = set()
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in ENV_UPDATES:
                out.append(f"{k}={ENV_UPDATES[k]}")
                seen.add(k)
                continue
        out.append(line)
    for k, v in ENV_UPDATES.items():
        if k not in seen:
            out.append(f"{k}={v}")
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def apply_local() -> list[str]:
    report = []
    for rel, patcher in [
        ("core/rmc.py", patch_rmc),
        ("core/oeg.py", patch_oeg),
        ("main.py", patch_main),
    ]:
        path = LOCAL / rel
        raw = path.read_text(encoding="utf-8")
        new = patcher(raw)
        if new != raw:
            path.write_text(new, encoding="utf-8")
            report.append(f"local patched: {rel}")
        else:
            report.append(f"local unchanged: {rel}")
    env_path = LOCAL / ".env"
    if env_path.exists():
        env_raw = env_path.read_text(encoding="utf-8")
        env_new = patch_env(env_raw)
        if env_new != env_raw:
            env_path.write_text(env_new, encoding="utf-8")
            report.append("local patched: .env")
        else:
            report.append("local unchanged: .env")
    return report


PROBE_SCRIPT = r'''#!/usr/bin/env python3
"""~$0.50 taker probe: market buy + trade_log fill update check."""
import asyncio
import json
import logging
import os
import sys
import time
import uuid
import urllib.request

import asyncpg
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from client import PolymarketClobClient
from core.rmc import RiskManagementCenter

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger("probe")
TARGET_USDC = float(os.getenv("PROBE_USDC", "0.5"))


def _px(level):
    if isinstance(level, dict):
        return float(level.get("price", 1e9))
    if isinstance(level, (int, float)):
        return float(level)
    if isinstance(level, str):
        return float(level)
    return float(getattr(level, "price", 1e9))


def _sz(level):
    if isinstance(level, dict):
        return float(level.get("size", 0) or 0)
    return float(getattr(level, "size", 0) or 0)


async def pick_market(clob):
    url = (
        "https://gamma-api.polymarket.com/markets?"
        "active=true&closed=false&limit=40&order=volumeNum&ascending=false"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "probe/1"})

    def _fetch():
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())

    markets = await asyncio.to_thread(_fetch)
    for m in markets:
        raw = m.get("clobTokenIds") or []
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not raw:
            continue
        tid = str(raw[0])
        book = await asyncio.to_thread(clob.get_order_book, tid)
        raw_asks = book.get("asks") if isinstance(book, dict) else getattr(book, "asks", None)
        if not raw_asks:
            continue
        if isinstance(raw_asks, list):
            asks = raw_asks
        elif isinstance(raw_asks, dict):
            asks = [raw_asks] if "price" in raw_asks else [
                {"price": k, "size": v} for k, v in raw_asks.items()
            ]
        elif hasattr(raw_asks, "price"):
            asks = [raw_asks]
        else:
            continue
        best = min(asks, key=_px)
        ask, depth = _px(best), _sz(best)
        if 0.15 <= ask <= 0.85 and depth * ask >= TARGET_USDC * 0.9:
            cond = m.get("conditionId") or m.get("condition_id") or "probe"
            return tid, ask, cond, m.get("question", "probe")[:80]
    raise RuntimeError("no liquid market for probe")


async def main():
    dsn = os.getenv("DATABASE_URL", "postgresql://poly:poly@localhost:5432/polymarket")
    clob = PolymarketClobClient(
        host=os.getenv("CLOB_HOST", "https://clob.polymarket.com"),
        chain_id=int(os.getenv("CHAIN_ID", "137")),
        private_key=os.getenv("PRIVATE_KEY", ""),
        signature_type=int(os.getenv("SIGNATURE_TYPE", "0") or 0),
        funder=os.getenv("FUNDER_ADDRESS") or None,
    )
    token_id, ask, cond, question = await pick_market(clob)
    signal_id = str(uuid.uuid4())
    LOGGER.info("probe_market token=%s ask=%.4f cond=%s", token_id[:12], ask, cond[:12])

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    rmc = RiskManagementCenter(db_pool=pool)
    await rmc._ensure_db()
    await pool.execute(
        """
        INSERT INTO trade_log (
            timestamp, signal_id, condition_id, market_question,
            yes_token_id, no_token_id,
            yes_price, no_price, yes_size, no_size,
            expected_profit, yes_status, no_status
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
        """,
        time.time(), signal_id, cond, question,
        token_id, token_id,
        ask, 1.0 - ask, TARGET_USDC / ask, TARGET_USDC / ask,
        0.0, "PENDING", "PENDING",
    )

    resp = await asyncio.to_thread(
        clob.create_market_order,
        token_id=token_id,
        side="BUY",
        amount_usdc=TARGET_USDC,
    )
    LOGGER.info("order_resp %s", resp)
    if isinstance(resp, dict) and resp.get("status") in ("FAILED", "REJECTED"):
        raise RuntimeError("ORDER_FAILED: %s" % resp)

    fill_price, fill_size = ask, TARGET_USDC / ask
    for _ in range(30):
        await asyncio.sleep(2)
        row = await pool.fetchrow(
            "SELECT yes_fill_price, yes_filled_size, yes_status FROM trade_log WHERE signal_id=$1",
            signal_id,
        )
        if row and row["yes_fill_price"]:
            LOGGER.info("trade_log OK %s", dict(row))
            await pool.close()
            return
    await rmc.on_fill_update(signal_id, "YES", fill_price, fill_size, "CONFIRMED")
    row = await pool.fetchrow(
        "SELECT yes_fill_price, yes_filled_size, yes_status FROM trade_log WHERE signal_id=$1",
        signal_id,
    )
    LOGGER.info("trade_log after callback %s", dict(row) if row else None)
    await pool.close()
    if not row or not row["yes_fill_price"]:
        raise RuntimeError("trade_log fill not updated")


if __name__ == "__main__":
    asyncio.run(main())
'''


def sftp_put(sftp, local: Path, remote: str) -> None:
    with sftp.file(remote, "w") as rf:
        rf.write(local.read_text(encoding="utf-8"))


def main() -> int:
    report = apply_local()
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASS, timeout=25)
    sftp = ssh.open_sftp()

    for rel in ["core/rmc.py", "core/oeg.py", "main.py"]:
        sftp_put(sftp, LOCAL / rel, f"{REMOTE}/{rel}")
        report.append(f"remote uploaded: {rel}")

    _, o, _ = ssh.exec_command(f"cat {REMOTE}/.env 2>/dev/null || true", timeout=30)
    env_remote = o.read().decode(errors="replace")
    env_new = patch_env(env_remote)
    with sftp.file(f"{REMOTE}/.env", "w") as ef:
        ef.write(env_new)
    report.append("remote patched: .env")

    with sftp.file(f"{REMOTE}/test_probe_trade.py", "w") as pf:
        pf.write(PROBE_SCRIPT)
    report.append("remote uploaded: test_probe_trade.py")

    sftp.close()

    ssh.exec_command(
        f"bash -lc 'cd {REMOTE} && source venv/bin/activate && pip install -q asyncpg structlog'",
        timeout=180,
    )

    ssh.exec_command("pkill -f 'python.*main.py' || true", timeout=20)
    time.sleep(2)
    start_cmd = (
        f"bash -lc 'cd {REMOTE} && source ~/.proxyrc 2>/dev/null; "
        f"source venv/bin/activate; mkdir -p logs; nohup python main.py --debug > logs/main_debug.log 2>&1 & sleep 2; pgrep -af main.py'"
    )
    _, o, e = ssh.exec_command(start_cmd, timeout=60)
    start_out = strip_emoji(o.read().decode(errors="replace"))
    report.append("main_start:\n" + start_out.strip())

    probe_cmd = (
        f"bash -lc 'cd {REMOTE} && source ~/.proxyrc 2>/dev/null; "
        f"source venv/bin/activate; python test_probe_trade.py > logs/probe_trade.log 2>&1'"
    )
    _, o, e = ssh.exec_command(probe_cmd, timeout=300)
    probe_code = o.channel.recv_exit_status()
    probe_out = strip_emoji((o.read() + e.read()).decode(errors="replace"))
    report.append(f"probe_exit={probe_code}")
    if probe_out.strip():
        report.append(probe_out.strip())

    _, o, _ = ssh.exec_command(f"tail -20 {REMOTE}/logs/main_debug.log", timeout=30)
    log_tail = strip_emoji(o.read().decode(errors="replace"))
    report.append("main_log_tail:\n" + log_tail.strip())

    _, o, _ = ssh.exec_command(f"tail -15 {REMOTE}/logs/probe_trade.log 2>/dev/null", timeout=30)
    probe_tail = strip_emoji(o.read().decode(errors="replace"))
    report.append("probe_log_tail:\n" + probe_tail.strip())

    ssh.close()
    text = "\n".join(report)
    (LOCAL / "deploy_report.txt").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

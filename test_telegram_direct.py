#!/usr/bin/env python3
"""Test Telegram send directly"""
import asyncio, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")
proxy_rc = Path.home() / ".proxyrc"
if proxy_rc.exists():
    for line in proxy_rc.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" in line and not line.startswith("#"):
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

from core.telegram_notify import send_message

async def test():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    proxy = os.environ.get("https_proxy", "none")
    print(f"proxy: {proxy}")
    print(f"token: {token[:8]}...{token[-4:]}")
    print(f"chat_id: {chat_id}")

    ok = await send_message(token, chat_id, "Maker strategy active!")
    print(f"send result: {ok}")

asyncio.run(test())
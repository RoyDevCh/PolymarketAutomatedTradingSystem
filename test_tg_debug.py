#!/usr/bin/env python3
"""Debug Telegram send from systemd-like environment"""
import asyncio, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

# Clear lowercase proxy vars (simulate systemd where only uppercase are set)
for k in ["http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(k, None)

# Ensure uppercase are set (as per systemd Environment=)
os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7890"
os.environ["HTTP_PROXY"] = "http://127.0.0.1:7890"
os.environ["ALL_PROXY"] = "socks5://127.0.0.1:7890"

import aiohttp

async def test():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    print(f"Lowercase https_proxy: {os.environ.get('https_proxy', 'NOT SET')}")
    print(f"Uppercase HTTPS_PROXY: {os.environ.get('HTTPS_PROXY', 'NOT SET')}")
    
    # Test 1: trust_env=True only (no explicit proxy)
    print("\n--- Test 1: trust_env=True + no explicit proxy ---")
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10), trust_env=True) as session:
            async with session.post(url, json={"chat_id": chat_id, "text": "Test1: trust_env only"}) as resp:
                print(f"  status={resp.status}")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {str(e)[:200]}")
    
    # Test 2: explicit proxy param (current code path)
    print("\n--- Test 2: explicit proxy= param ---")
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10), trust_env=True) as session:
            async with session.post(url, json={"chat_id": chat_id, "text": "Test2: explicit proxy"}, proxy="http://127.0.0.1:7890") as resp:
                print(f"  status={resp.status}")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {str(e)[:200]}")
    
    # Test 3: no trust_env, explicit proxy only
    print("\n--- Test 3: no trust_env + explicit proxy ---")
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10), trust_env=False) as session:
            async with session.post(url, json={"chat_id": chat_id, "text": "Test3: no trust_env"}, proxy="http://127.0.0.1:7890") as resp:
                print(f"  status={resp.status}")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {str(e)[:200]}")

asyncio.run(test())
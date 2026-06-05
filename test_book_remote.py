#!/usr/bin/env python3
"""Debug: test order book fetch on remote server."""
import os
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.3.117", username="roy", password=os.getenv("REMOTE_PASSWORD",""), timeout=15)

script = r"""
import os, sys, json
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")
from pathlib import Path
proxy_rc = Path.home() / ".proxyrc"
if proxy_rc.exists():
    for line in proxy_rc.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" in line and not line.startswith("#"):
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

import httpx
import py_clob_client_v2.http_helpers.helpers as _v2h
proxy_url = os.environ.get("https_proxy") or os.environ.get("http_proxy")
if proxy_url:
    _v2h._http_client = httpx.Client(proxy=proxy_url, timeout=httpx.Timeout(30.0), follow_redirects=True)

from core.clob_client import get_clob_client
try:
    c = get_clob_client()
    print("client ready, sig_type:", c.signature_type)
except Exception as e:
    print("client error:", e)
    sys.exit(1)

# Get one market's token
import asyncio, aiohttp
async def fetch():
    session = aiohttp.ClientSession(trust_env=True)
    url = "https://gamma-api.polymarket.com/markets"
    params = {"active":"true","closed":"false","order":"volume","ascending":"false","limit":3}
    proxy = os.environ.get("https_proxy")
    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15), proxy=proxy) as resp:
        data = await resp.json()
    await session.close()
    return data

markets = asyncio.run(fetch())
for m in markets[:3]:
    q = m.get("question","")[:50]
    tokens = m.get("clobTokenIds", [])
    if isinstance(tokens, str):
        tokens = json.loads(tokens)
    tid = tokens[0] if tokens else ""
    print(f"\nMarket: {q}")
    print(f"Token: {tid[:30]}...")
    try:
        book = c.get_order_book(tid)
        if book and book.asks:
            print(f"  asks: {len(book.asks)}, best ask: price={book.asks[0].price} size={book.asks[0].size}")
        else:
            print(f"  book: {type(book)} = {book}")
    except Exception as e:
        print(f"  get_order_book error: {type(e).__name__}: {e}")
"""

sftp = ssh.open_sftp()
sftp.put("/dev/stdin", "/home/roy/polymarket-arb/test_book_fetch.py")
sftp.close()

# Write the script to remote
import tempfile, shutil
with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
    f.write(script)
    tmp_path = f.name

sftp = ssh.open_sftp()
sftp.put(tmp_path, "/home/roy/polymarket-arb/test_book_fetch.py")
sftp.close()

_, stdout, stderr = ssh.exec_command(
    "cd /home/roy/polymarket-arb && source venv/bin/activate && source ~/.proxyrc && python3 test_book_fetch.py 2>&1",
    timeout=60
)
print(stdout.read().decode('utf-8', errors='replace'))
ssh.close()
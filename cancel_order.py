import os
from pathlib import Path
import httpx, py_clob_client_v2.http_helpers.helpers as _v2h
from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import ApiCreds

ORDER_ID = "0x33c66e58ff9f14afcce290d8ed303b0d1ccfe487e8bbafe36354a59156e1b622"

for line in Path("/home/roy/polymarket-arb/.env").read_text().splitlines():
    line = line.strip()
    if line.startswith("#") or not line or "=" not in line: continue
    k, _, v = line.partition("=")
    os.environ.setdefault(k.strip(), v.strip())

proxy = os.environ.get("https_proxy")
if proxy: _v2h._http_client = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True)

client = ClobClient(host="https://clob.polymarket.com", key=os.environ["PRIVATE_KEY"], chain_id=137,
    creds=ApiCreds(api_key=os.environ["API_KEY"], api_secret=os.environ["API_SECRET"],
                   api_passphrase=os.environ["API_PASSPHRASE"]),
    signature_type=3, funder=os.environ["DEPOSIT_WALLET"])

methods = [m for m in dir(client) if "cancel" in m.lower()]
print("Cancel methods:", methods)

for method in ["cancel", "cancel_order", "cancel_orders"]:
    if hasattr(client, method):
        try:
            fn = getattr(client, method)
            result = fn(ORDER_ID) if method != "cancel_orders" else fn([ORDER_ID])
            print(f"{method}: {result}")
        except Exception as e:
            print(f"{method} error: {e}")

try:
    print("cancel_all:", client.cancel_all())
except Exception as e:
    print(f"cancel_all error: {e}")

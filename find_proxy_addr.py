import os, sys
sys.path.insert(0, ".")
from pathlib import Path
proxy_rc = Path.home() / ".proxyrc"
if proxy_rc.exists():
    for line in proxy_rc.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" in line and not line.startswith("#"):
            key, _, val = line.partition("=")
            if key.strip().lower().endswith("_proxy") and val.strip():
                os.environ.setdefault(key.strip(), val.strip())

from web3 import Web3
from core.config import CONFIG

w3 = Web3(Web3.HTTPProvider(CONFIG.wallet.rpc_url or "https://polygon-bor-rpc.publicnode.com"))
eoa = w3.eth.account.from_key(CONFIG.wallet.private_key).address
print(f"EOA: {eoa}")

code = w3.eth.get_code(eoa)
print(f"Code at EOA: {len(code)} bytes ({'CONTRACT' if len(code) > 0 else 'EOA'})")

EXCHANGE_V2 = "0xE111180000d2663C0091e4f400237545B87B996B"
NEGRISK_V2 = "0xe2222d279d744050d28e00520010520000310F59"

selector = Web3.keccak(text="getSafeWalletAddress(address)")[:4].hex()
data = "0x" + selector + eoa[2:].zfill(64).lower()

for name, addr in [("V2 Exchange", EXCHANGE_V2), ("NegRisk V2", NEGRISK_V2)]:
    try:
        result = w3.eth.call({"to": addr, "data": data})
        proxy_addr = "0x" + result.hex()[-40:]
        print(f"Proxy wallet ({name}): {proxy_addr}")
        proxy_code = w3.eth.get_code(proxy_addr)
        print(f"  Code at proxy: {len(proxy_code)} bytes ({'DEPLOYED' if len(proxy_code) > 0 else 'NOT DEPLOYED'})")
    except Exception as e:
        print(f"getSafeWalletAddress ({name}): {e}")
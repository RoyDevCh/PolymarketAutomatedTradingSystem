"""Deploy deposit wallet and verify"""
import os, sys, json
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

import httpx
from web3 import Web3
from core.config import CONFIG

EOA = "0x43083C461fc9b875c97032f375bf8aef81681B8e"
DEPOSIT_WALLET = "0x81F8e53Ab8AA315FB5F2d81D08C93aDbb257A548"
FACTORY = "0x00000000000Fb5C9ADea0298D729A0CB3823Cc07"
RELAYER_URL = "https://poly-relayer-api.polymarket.com"

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))

# Check deployment status
code = w3.eth.get_code(Web3.to_checksum_address(DEPOSIT_WALLET))
deployed = len(code) > 0
print(f"Deposit wallet: {DEPOSIT_WALLET}")
print(f"Deployed: {deployed} ({len(code)} bytes)")

# Also check V2 Exchange safe wallet
EXCHANGE_V2 = "0xE111180000d2663C0091e4f400237545B87B996B"
selector = Web3.keccak(text="getSafeWalletAddress(address)")[:4].hex()
data_hex = "0x" + selector + EOA[2:].zfill(64).lower()
result = w3.eth.call({"to": EXCHANGE_V2, "data": data_hex})
safe_addr = "0x" + result.hex()[-40:]
print(f"V2 Exchange getSafeWalletAddress: {safe_addr}")
print(f"Matches deposit wallet: {safe_addr.lower() == DEPOSIT_WALLET.lower()}")

# Try deploying via relayer
proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
client = httpx.Client(proxy=proxy, timeout=httpx.Timeout(30.0), follow_redirects=True)

payload = {
    "type": "WALLET-CREATE",
    "from": EOA,
    "to": FACTORY,
}

print(f"\nDeploying deposit wallet...")
print(f"Payload: {json.dumps(payload)}")

try:
    resp = client.post(
        f"{RELAYER_URL}/submit",
        json=payload,
        headers={"Content-Type": "application/json"},
    )
    print(f"Status: {resp.status_code}")
    print(f"Body: {resp.text[:500]}")
    
    if resp.status_code in [200, 201]:
        print("\n[OK] Deployment request accepted!")
        # Poll for confirmation
        import time
        for i in range(30):
            time.sleep(2)
            code_check = w3.eth.get_code(Web3.to_checksum_address(DEPOSIT_WALLET))
            if len(code_check) > 0:
                print(f"\n[OK] Deposit wallet DEPLOYED! ({len(code_check)} bytes)")
                break
            print(f"  Waiting... ({i+1}/30)")
        else:
            print("\n[WARN] Deployment not confirmed within 60 seconds")
    else:
        print(f"\n[FAIL] Deployment request rejected")
except Exception as e:
    print(f"\n[FAIL] {type(e).__name__}: {e}")

# Verify final state
code_final = w3.eth.get_code(Web3.to_checksum_address(DEPOSIT_WALLET))
print(f"\nFinal code at deposit wallet: {len(code_final)} bytes")
if len(code_final) > 0:
    print("[OK] Deposit wallet is DEPLOYED and ready for V2 orders!")
else:
    print("[WARN] Deposit wallet NOT deployed yet")
    print("Next step: Access polymarket.com through a US/JP VPN and make a small trade")
    print("This will trigger the deposit wallet deployment automatically.")
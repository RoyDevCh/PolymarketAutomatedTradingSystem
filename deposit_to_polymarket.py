"""Deposit USDC from EOA to Polymarket proxy wallet and sync CLOB balance."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")

# Load proxy
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

# Load env
for line in Path("/home/roy/polymarket-arb/.env").read_text().splitlines():
    line = line.strip()
    if line.startswith("#") or not line or "=" not in line:
        continue
    key, _, val = line.partition("=")
    os.environ.setdefault(key.strip(), val.strip())

from eth_account import Account
from web3 import Web3

import httpx
import py_clob_client_v2.http_helpers.helpers as _v2h

proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
if proxy:
    _v2h._http_client = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True)

from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import ApiCreds, BalanceAllowanceParams, AssetType

pk = os.environ["PRIVATE_KEY"]
eoa = Account.from_key(pk).address
DEPOSIT = os.environ["DEPOSIT_WALLET"]
SIG_TYPE = int(os.environ.get("SIGNATURE_TYPE", "3"))

USDC = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
EXCHANGE = Web3.to_checksum_address("0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E")
RPC = "https://polygon-bor-rpc.publicnode.com"

ERC20_ABI = [
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf",
     "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
     "name": "allowance", "outputs": [{"name": "", "type": "uint256"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "recipient", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "name": "transfer", "outputs": [{"name": "", "type": "bool"}],
     "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "name": "approve", "outputs": [{"name": "", "type": "bool"}],
     "stateMutability": "nonpayable", "type": "function"},
]

print("=" * 60)
print("Deposit USDC to Polymarket Proxy Wallet")
print("=" * 60)
print(f"EOA:     {eoa}")
print(f"Deposit: {DEPOSIT}")

w3 = Web3(Web3.HTTPProvider(RPC))
usdc = w3.eth.contract(address=USDC, abi=ERC20_ABI)
eoa_cs = Web3.to_checksum_address(eoa)
deposit_cs = Web3.to_checksum_address(DEPOSIT)

# Check balances
eoa_usdc = usdc.functions.balanceOf(eoa_cs).call()
dep_usdc = usdc.functions.balanceOf(deposit_cs).call()
allowance = usdc.functions.allowance(deposit_cs, EXCHANGE).call()
code_len = len(w3.eth.get_code(deposit_cs))

print(f"\nOn-chain status:")
print(f"  EOA USDC:     {eoa_usdc / 1e6:.2f}")
print(f"  Deposit USDC: {dep_usdc / 1e6:.2f}")
print(f"  Allowance to exchange: {allowance / 1e6:.2f}")
print(f"  Deposit code: {code_len} bytes")

# Step 1: Transfer USDC to deposit wallet
TRANSFER_USDC = 45.0  # leave ~4 USDC on EOA
if eoa_usdc / 1e6 < TRANSFER_USDC + 1:
    TRANSFER_USDC = max(0, eoa_usdc / 1e6 - 1)

if dep_usdc / 1e6 < 40 and TRANSFER_USDC >= 3:
    amount_wei = int(TRANSFER_USDC * 1e6)
    print(f"\n--- Step 1: Transfer {TRANSFER_USDC:.2f} USDC to deposit wallet ---")
    nonce = w3.eth.get_transaction_count(eoa_cs)
    gas_price = w3.eth.gas_price
    tx = usdc.functions.transfer(deposit_cs, amount_wei).build_transaction({
        "from": eoa_cs, "gas": 100000, "gasPrice": gas_price,
        "nonce": nonce, "chainId": 137,
    })
    signed = w3.eth.account.sign_transaction(tx, pk)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"TX: {tx_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    print(f"Status: {'OK' if receipt.status == 1 else 'FAILED'}")
    if receipt.status != 1:
        print("Transfer failed, aborting.")
        sys.exit(1)
    dep_usdc = usdc.functions.balanceOf(deposit_cs).call()
    print(f"Deposit USDC after transfer: {dep_usdc / 1e6:.2f}")
else:
    print(f"\n--- Step 1: Skip transfer (deposit already has {dep_usdc/1e6:.2f} USDC) ---")

# Step 2: Sync CLOB balance via API
print("\n--- Step 2: Sync CLOB balance ---")
creds = ApiCreds(
    api_key=os.environ["API_KEY"],
    api_secret=os.environ["API_SECRET"],
    api_passphrase=os.environ["API_PASSPHRASE"],
)
client = ClobClient(
    host="https://clob.polymarket.com",
    key=pk, chain_id=137, creds=creds,
    signature_type=SIG_TYPE, funder=DEPOSIT,
)
if proxy:
    _v2h._http_client = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True)

params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=SIG_TYPE)

try:
    sync_result = client.update_balance_allowance(params)
    print(f"Sync result: {sync_result}")
except Exception as e:
    print(f"Sync error: {type(e).__name__}: {str(e)[:200]}")

time.sleep(2)

try:
    bal = client.get_balance_allowance(params)
    print(f"CLOB balance: {bal}")
except Exception as e:
    print(f"Balance query error: {type(e).__name__}: {str(e)[:200]}")

# Step 3: If allowance is 0, try approving via relayer
allowance = usdc.functions.allowance(deposit_cs, EXCHANGE).call()
if allowance < dep_usdc:
    print(f"\n--- Step 3: Allowance insufficient ({allowance/1e6:.2f}), trying relayer approve ---")
    try:
        # Build approve calldata for proxy wallet execution via relayer
        approve_data = usdc.encode_abi("approve", [EXCHANGE, 2**256 - 1])
        relayer_key = os.environ.get("RELAYER_API_KEY", os.environ.get("API_KEY", ""))
        relayer_addr = os.environ.get("RELAYER_API_KEY_ADDRESS", eoa)
        headers = {
            "RELAYER_API_KEY": relayer_key,
            "RELAYER_API_KEY_ADDRESS": relayer_addr,
            "Content-Type": "application/json",
        }
        hc = httpx.Client(proxy=proxy, timeout=30.0, follow_redirects=True) if proxy else httpx.Client(timeout=30.0)

        # Get nonce
        nonce_resp = hc.get(
            "https://relayer-v2.polymarket.com/nonce",
            params={"address": eoa, "type": "SAFE"},
            headers=headers,
        )
        print(f"Relayer nonce: {nonce_resp.status_code} {nonce_resp.text[:200]}")

        payload_resp = hc.get(
            "https://relayer-v2.polymarket.com/relay-payload",
            params={"address": eoa, "type": "SAFE"},
            headers=headers,
        )
        print(f"Relay payload: {payload_resp.status_code} {payload_resp.text[:300]}")

        # Submit approve transaction via relayer
        submit_body = {
            "from": eoa,
            "to": USDC,
            "proxyWallet": DEPOSIT,
            "data": approve_data,
            "nonce": nonce_resp.json().get("nonce", "0") if nonce_resp.status_code == 200 else "0",
            "signature": "0x",
            "signatureParams": {
                "gasPrice": "0",
                "operation": "0",
                "safeTxnGas": "0",
                "baseGas": "0",
                "gasToken": "0x0000000000000000000000000000000000000000",
                "refundReceiver": "0x0000000000000000000000000000000000000000",
            },
            "type": "SAFE",
        }
        submit_resp = hc.post(
            "https://relayer-v2.polymarket.com/submit",
            json=submit_body,
            headers=headers,
        )
        print(f"Relayer submit: {submit_resp.status_code} {submit_resp.text[:300]}")
    except Exception as e:
        print(f"Relayer approve error: {type(e).__name__}: {str(e)[:200]}")
        print("Note: Approval may need to be done via Polymarket website Enable Trading")

    # Re-sync after approve attempt
    time.sleep(3)
    try:
        client.update_balance_allowance(params)
        bal = client.get_balance_allowance(params)
        print(f"CLOB balance after approve attempt: {bal}")
    except Exception as e:
        print(f"Re-sync error: {str(e)[:150]}")

print("\n--- Done ---")
print(f"Deposit wallet USDC: {usdc.functions.balanceOf(deposit_cs).call() / 1e6:.2f}")
print(f"Allowance: {usdc.functions.allowance(deposit_cs, EXCHANGE).call() / 1e6:.2f}")

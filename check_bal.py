import requests

addr = "0x43083C461fc9b875c97032f375bf8aef81681B8e"
rpc = "https://polygon-bor-rpc.publicnode.com"
data_sig = "0x70a08231" + addr[2:].lower().zfill(64)

# POL
r = requests.post(rpc, json={"jsonrpc":"2.0","method":"eth_getBalance","params":[addr,"latest"],"id":1}, timeout=10)
pol = int(r.json()["result"], 16) / 1e18
print(f"POL: {pol:.4f} (~${pol*0.19:.2f})")

# USDC.e (bridged)
r = requests.post(rpc, json={"jsonrpc":"2.0","method":"eth_call","params":[{"to":"0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174","data":data_sig},"latest"],"id":2}, timeout=10)
usdc_e = int(r.json()["result"], 16) / 1e6
print(f"USDC.e (bridged): {usdc_e:.2f}")

# USDC (native)
r = requests.post(rpc, json={"jsonrpc":"2.0","method":"eth_call","params":[{"to":"0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359","data":data_sig},"latest"],"id":3}, timeout=10)
usdc_n = int(r.json()["result"], 16) / 1e6
print(f"USDC (native): {usdc_n:.2f}")

total = pol * 0.19 + usdc_e + usdc_n
print(f"\nTotal USD: ~${total:.2f}")
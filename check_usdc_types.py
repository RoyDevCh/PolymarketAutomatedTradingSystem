"""Check native USDC vs Polymarket collateral token balances."""
from web3 import Web3
from py_clob_client_v2.config import get_contract_config

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
cfg = get_contract_config(137)

NATIVE_USDC = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
BRIDGED_USDC = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
PM_COLLATERAL = Web3.to_checksum_address(cfg.collateral)

addrs = {
    "EOA": "0xE56A44444F55aD30C87235f7C94786509881Da3A",
    "Deposit": "0x181242c978fb34c26068f8B154126F8Ea745C88B",
}

tokens = {
    "Native USDC": NATIVE_USDC,
    "Bridged USDC.e": BRIDGED_USDC,
    "PM Collateral": PM_COLLATERAL,
}

abi = [{"inputs":[{"name":"account","type":"address"}],"name":"balanceOf",
        "outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]

print(f"PM Collateral address: {PM_COLLATERAL}")
print(f"Exchange: {cfg.exchange}")
print()

for name, addr in addrs.items():
    ca = Web3.to_checksum_address(addr)
    print(f"{name} ({addr[:10]}...):")
    for tname, taddr in tokens.items():
        try:
            c = w3.eth.contract(address=taddr, abi=abi)
            bal = c.functions.balanceOf(ca).call() / 1e6
            print(f"  {tname}: {bal:.6f}")
        except Exception as e:
            print(f"  {tname}: error {e}")
    print()

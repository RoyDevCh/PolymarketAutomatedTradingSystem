from web3 import Web3
from py_clob_client_v2.config import get_contract_config

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
cfg = get_contract_config(137)

tokens = {
    "Native USDC": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
    "USDC.e": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
    "PM Collateral": cfg.collateral,
}
abi = [
    {"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"name","outputs":[{"name":"","type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"stateMutability":"view","type":"function"},
]
for tname, addr in tokens.items():
    c = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=abi)
    print(f"{tname} ({addr}):")
    print(f"  name={c.functions.name().call()}, symbol={c.functions.symbol().call()}, decimals={c.functions.decimals().call()}")

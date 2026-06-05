from web3 import Web3
from py_clob_client_v2.config import get_contract_config

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
cfg = get_contract_config(137)
NATIVE = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
PUSD = Web3.to_checksum_address(cfg.collateral)

addrs = {
    "Deposit": "0x181242c978fb34c26068f8B154126F8Ea745C88B",
    "Proxy": "0x52A08c191319a9bd3bA65b8F7D008660c74C78cf",
    "EOA": "0xE56A44444F55aD30C87235f7C94786509881Da3A",
}
abi = [{"inputs":[{"name":"account","type":"address"}],"name":"balanceOf",
        "outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]

for name, addr in addrs.items():
    ca = Web3.to_checksum_address(addr)
    code = len(w3.eth.get_code(ca))
    usdc = w3.eth.contract(address=NATIVE, abi=abi).functions.balanceOf(ca).call()/1e6
    pusd = w3.eth.contract(address=PUSD, abi=abi).functions.balanceOf(ca).call()/1e6
    print(f"{name}: code={code}, USDC={usdc:.2f}, pUSD={pusd:.2f}")

"""Probe pUSD and deposit wallet contract interfaces."""
from web3 import Web3

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
PUSD = Web3.to_checksum_address("0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB")
NATIVE_USDC = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
DEPOSIT = Web3.to_checksum_address("0x181242c978fb34c26068f8B154126F8Ea745C88B")
IMPL = Web3.to_checksum_address("0x58CA52ebe0DadfdF531Cde7062e76746de4Db1eB")

# Common function selectors to probe on pUSD
selectors = {
    "deposit(uint256)": "0xb6b55f25",
    "depositFor(address,uint256)": None,
    "mint(uint256)": "0xa0712d68",
    "convert(uint256)": None,
    "wrap(uint256)": None,
}

# Get bytecode and try implementation
for name, addr in [("Deposit Wallet", DEPOSIT), ("Implementation", IMPL), ("pUSD", PUSD)]:
    code = w3.eth.get_code(addr)
    print(f"{name} ({addr[:10]}...): {len(code)} bytes")

# Try to call pUSD with common ABIs
pusd_abi_candidates = [
    {"inputs":[{"name":"amount","type":"uint256"}],"name":"deposit","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"to","type":"address"},{"name":"amount","type":"uint256"}],"name":"depositFor","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[],"name":"underlying","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"usdc","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"asset","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"},
]
pusd = w3.eth.contract(address=PUSD, abi=pusd_abi_candidates)
for fn in ["underlying", "usdc", "asset"]:
    try:
        val = getattr(pusd.functions, fn)().call()
        print(f"pUSD.{fn}() = {val}")
    except Exception as e:
        print(f"pUSD.{fn}(): {type(e).__name__}")

# Check if deposit wallet can receive and what token balances it should hold
erc20_abi = [{"inputs":[{"name":"account","type":"address"}],"name":"balanceOf",
              "outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]
for tname, taddr in [("Native USDC", NATIVE_USDC), ("pUSD", PUSD)]:
    c = w3.eth.contract(address=taddr, abi=erc20_abi)
    bal = c.functions.balanceOf(DEPOSIT).call() / 1e6
    print(f"Deposit wallet {tname}: {bal:.4f}")

# Try reading deposit wallet implementation slot (EIP-1967)
slot = int("0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc", 16)
impl_raw = w3.eth.get_storage_at(DEPOSIT, slot)
impl_addr = Web3.to_checksum_address("0x" + impl_raw.hex()[-40:])
print(f"Deposit wallet implementation (EIP-1967): {impl_addr}")

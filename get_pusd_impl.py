from web3 import Web3
w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
PUSD = Web3.to_checksum_address("0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB")
slot = int("0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc", 16)
impl_raw = w3.eth.get_storage_at(PUSD, slot)
impl = Web3.to_checksum_address("0x" + impl_raw.hex()[-40:])
print(f"pUSD implementation: {impl}")
print(f"Code size: {len(w3.eth.get_code(impl))} bytes")

# Try common view functions on implementation
abi = [
    {"inputs":[],"name":"name","outputs":[{"name":"","type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"underlying","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"asset","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"collateral","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"},
]
c = w3.eth.contract(address=impl, abi=abi)
for fn in ["name", "underlying", "asset", "collateral"]:
    try:
        print(f"{fn}(): {getattr(c.functions, fn)().call()}")
    except Exception as e:
        print(f"{fn}(): {type(e).__name__}")

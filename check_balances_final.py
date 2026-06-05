from web3 import Web3

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))

addrs = {
    "Polymarket_provided": "0xAe886C5740F6614e0300BC2AF95e730f150685Ff",
    "Our_EOA": "0xE56A44444F55aD30C87235f7C94786509881Da3A",
    "Our_deposit_wallet": "0x181242c978fb34c26068f8B154126F8Ea745C88B",
}

USDC = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
erc20_abi = [{"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}]
usdc = w3.eth.contract(address=USDC, abi=erc20_abi)

print("Address                                    Code   MATIC      USDC   Status")
print("-" * 80)
for name, addr in addrs.items():
    ca = Web3.to_checksum_address(addr)
    code = w3.eth.get_code(ca)
    matic = w3.from_wei(w3.eth.get_balance(ca), "ether")
    usdc_bal = usdc.functions.balanceOf(ca).call() / 1e6
    status = "DEPLOYED!" if len(code) > 0 else "EOA"
    print(f"{name:<20} {addr[:10]}...{addr[-6:]}  {len(code):>3}   {matic:>8.4f}  {usdc_bal:>7.2f}  {status}")

# Specifically check if Polymarket deposit wallet is now deployed
pm = Web3.to_checksum_address("0xAe886C5740F6614e0300BC2AF95e730f150685Ff")
pm_code = w3.eth.get_code(pm)
print(f"\nPolymarket address 0xAe886C...: {len(pm_code)} bytes code")
if len(pm_code) > 0:
    print("[SUCCESS] Deposit wallet is NOW DEPLOYED!")
else:
    print("[INFO] Address is still EOA - USDC might be held in a different way")
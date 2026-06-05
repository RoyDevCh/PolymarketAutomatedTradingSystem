from web3 import Web3

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))

# Check all wallet addresses
addrs = {
    "Polymarket_provided": "0xAe886C5740F6614e0300BC2AF95e730f150685Ff",
    "Our_EOA": "0xE56A44444F55aD30C87235f7C94786509881Da3A",
    "Our_deposit_wallet": "0x181242c978fb34c26068f8B154126F8Ea745C88B",
    "Old_wallet": "0x43083C461fc9b875c97032f375bf8aef81681B8e",
    "V1_proxy": "0x4b34FA1Dc7047f03c63f04e7555B1dF6A94d2403",
}

USDC = Web3.to_checksum_address("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359")
erc20_abi = [{"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}]
usdc = w3.eth.contract(address=USDC, abi=erc20_abi)

print("=" * 70)
print(f"  {'Name':<25} {'Address':<20} {'Code':>5} {'MATIC':>10} {'USDC':>8}")
print("=" * 70)

for name, addr in addrs.items():
    ca = Web3.to_checksum_address(addr)
    code = w3.eth.get_code(ca)
    matic = w3.from_wei(w3.eth.get_balance(ca), "ether")
    usdc_bal = usdc.functions.balanceOf(ca).call() / 1e6
    code_type = "CONTRACT" if len(code) > 0 else "EOA"
    print(f"  {name:<25} {addr[:10]}...{addr[-6:]}  {len(code):>3}  {matic:>8.4f}  {usdc_bal:>7.2f}")
    if len(code) > 0 and len(code) < 100:
        print(f"    Code: {code.hex()[:80]}...")

print("=" * 70)
print()
print("Analysis:")
print(f"  0xAe886C... : {'Polymarket deposit wallet (needs deployment)' if len(w3.eth.get_code(Web3.to_checksum_address(addrs['Polymarket_provided']))) == 0 else 'Deployed contract'}")
print(f"  This address has 0 bytes code = it's an EOA (externally owned account)")
print(f"  Polymarket deposit wallets should be smart contracts with code > 0")
print()
print("Possible explanations:")
print("  1. This is NOT a Polymarket deposit wallet - it might be a Coinbase address")
print("  2. This address needs to be activated/deployed through Polymarket first")
print("  3. You might need to click 'Deposit' on Polymarket to get the correct address")
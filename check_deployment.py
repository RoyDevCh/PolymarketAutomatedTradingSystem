import os
from web3 import Web3

w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))

EOA = "OLD_EOA_PLACEHOLDER"
FUNDER = "OLD_FUNDER_PLACEHOLDER"

code_eoa = w3.eth.get_code(EOA)
code_funder = w3.eth.get_code(Web3.to_checksum_address(FUNDER))

print(f"EOA: {EOA}")
print(f"  Code: {len(code_eoa)} bytes")
print(f"  Is contract: {len(code_eoa) > 0}")

print(f"\nFunder (deposit wallet): {FUNDER}")
print(f"  Code: {len(code_funder)} bytes")
print(f"  Is deployed: {len(code_funder) > 0}")

# Check USDC balance
USDC_NATIVE = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
ERC20_ABI = [{"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}]
usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC_NATIVE), abi=ERC20_ABI)

try:
    bal_eoa = usdc.functions.balanceOf(Web3.to_checksum_address(EOA)).call()
    print(f"\nUSDC (native) balance on EOA: {bal_eoa / 1e6:.2f}")
except Exception as e:
    print(f"\nUSDC balance check error: {e}")

try:
    bal_funder = usdc.functions.balanceOf(Web3.to_checksum_address(FUNDER)).call()
    print(f"USDC (native) balance on Funder: {bal_funder / 1e6:.2f}")
except Exception as e:
    print(f"Funder USDC balance error: {e}")
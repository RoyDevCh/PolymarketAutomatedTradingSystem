"""
资金迁移脚本 - 将老钱包所有资金转入 Polymarket CLOB 账户

流程:
1. 老钱包 → EOA 钱包: 转 2 POL (gas fee)
2. 老钱包: 将 Native USDC 换成 USDC.e (通过 QuickSwap/1inch)
3. 老钱包 → EOA 钱包: 转 USDC.e
4. EOA 钱包: Approve USDC.e → Polymarket Exchange
5. EOA 钱包: Deposit USDC.e → CLOB 账户
6. (可选) 老钱包: 将剩余 POL 换成 USDC.e → 转 EOA → deposit

使用: python deploy_transfer_funds.py [--dry-run] [--step N]
"""

from __future__ import annotations

import os
import sys
import time
import json
from web3 import Web3
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# ============================================================
# 配置
# ============================================================
RPC_URL = 'https://omniscient-rough-wind.matic.quiknode.pro/7eec833eb14ae652439eb1d0bf71ea3ea4440e33/'
OLD_PRIVATE_KEY = '0x326a179abd83b7b50ea8933e06a02ab0bd4f07b37b0dcb38f73458e8eb9e828a'  # Old wallet
NEW_PRIVATE_KEY = os.getenv('PRIVATE_KEY', '')  # EOA wallet

OLD_WALLET = '0x43083C461fc9b875c97032f375bf8aef81681B8e'
EOA_WALLET = os.getenv('WALLET_ADDRESS', '0xE56A44444F55aD30C87235f7C94786509881Da3A')
DEPOSIT_WALLET = os.getenv('DEPOSIT_WALLET', '0x181242c978fb34c26068f8B154126F8Ea745C88B')

# Token addresses on Polygon
USDC_NATIVE = '0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359'  # Native USDC
USDC_E = '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174'      # USDC.e (Bridged)
WMATIC = '0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270'      # WMATIC

# QuickSwap Router V2
QUICKSWAP_ROUTER = '0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff'

# Polymarket contracts
NEG_RISK_EXCHANGE = '0xC5d563A36AE78145C45a50134d48A1215220f80a'  # Neg Risk Exchange
CTF_EXCHANGE = '0x4bFb41d5B3570DeFdE52a8fB0781244cd07aB14e'      # CTF Exchange (old)

# ERC20 ABI (minimal)
ERC20_ABI = json.loads('''[
    {"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},
    {"constant":true,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"},
    {"constant":false,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"},
    {"constant":true,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"remaining","type":"uint256"}],"type":"function"},
    {"constant":false,"inputs":[{"name":"_to","type":"address"},{"name":"_value","type":"uint256"}],"name":"transfer","outputs":[{"name":"","type":"bool"}],"type":"function"}
]''')

# QuickSwap Router ABI (minimal - swap and swapExactTokensForTokens)
ROUTER_ABI = json.loads('''[
    {"inputs":[{"name":"amountIn","type":"uint256"},{"name":"amountOutMin","type":"uint256"},{"name":"path","type":"address[]"},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactTokensForTokens","outputs":[{"name":"amounts","type":"uint256[]"}],"type":"function"},
    {"inputs":[{"name":"amountIn","type":"uint256"},{"name":"amountOutMin","type":"uint256"},{"name":"path","type":"address[]"},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactTokensForTokensSupportingFeeOnTransferTokens","outputs":[],"type":"function"},
    {"inputs":[{"name":"amountIn","type":"uint256"},{"name":"path","type":"address[]"}],"name":"getAmountsOut","outputs":[{"name":"amounts","type":"uint256[]"}],"type":"function"}
]''')

# Polymarket Exchange deposit ABI
EXCHANGE_ABI = json.loads('''[
    {"inputs":[{"name":"token","type":"address"},{"name":"amount","type":"uint256"}],"name":"deposit","outputs":[],"type":"function"}
]''')

w3 = Web3(Web3.HTTPProvider(RPC_URL))

# Setup accounts
old_account = w3.eth.account.from_key(OLD_PRIVATE_KEY)
new_account = w3.eth.account.from_key(NEW_PRIVATE_KEY) if NEW_PRIVATE_KEY else None

DRY_RUN = '--dry-run' in sys.argv


def check_balances():
    """检查所有钱包余额"""
    print("=" * 60)
    print("📊 当前余额")
    print("=" * 60)
    
    wallets = {
        'OLD_WALLET': OLD_WALLET,
        'EOA_WALLET': EOA_WALLET,
        'DEPOSIT_WALLET': DEPOSIT_WALLET,
    }
    
    total_usdc = 0
    
    for label, addr in wallets.items():
        addr_cs = Web3.to_checksum_address(addr)
        pol = float(w3.from_wei(w3.eth.get_balance(addr_cs), 'ether'))
        print(f"\n{label}: {addr}")
        print(f"  POL: {pol:.4f} (~${pol * 0.20:.2f})")
        
        for token_name, token_addr in [('USDC.e(Bridged)', USDC_E), ('USDC(Native)', USDC_NATIVE)]:
            contract = w3.eth.contract(
                address=Web3.to_checksum_address(token_addr),
                abi=ERC20_ABI
            )
            decimals = contract.functions.decimals().call()
            raw = contract.functions.balanceOf(addr_cs).call()
            balance = raw / (10 ** decimals)
            print(f"  {token_name}: {balance:.6f}")
            if 'USDC' in token_name:
                total_usdc += balance
    
    print(f"\n💰 总 USDC: {total_usdc:.6f}")
    return total_usdc


def step1_transfer_pol_for_gas():
    """Step 1: 从老钱包转 2 POL 到 EOA 钱包 (用于 gas)"""
    print("\n" + "=" * 60)
    print("Step 1: 转移 POL (gas fee) → EOA 钱包")
    print("=" * 60)
    
    amount_pol = 2.0  # 2 POL for gas
    amount_wei = w3.to_wei(amount_pol, 'ether')
    
    gas_price = w3.eth.gas_price
    gas_estimate = 21000  # Simple transfer
    gas_cost = gas_estimate * gas_price
    
    old_balance = w3.eth.get_balance(Web3.to_checksum_address(OLD_WALLET))
    print(f"老钱包 POL: {float(w3.from_wei(old_balance, 'ether')):.4f}")
    print(f"计划转账: {amount_pol} POL")
    print(f"预估 gas 费: {float(w3.from_wei(gas_cost, 'ether')):.6f} POL")
    
    if DRY_RUN:
        print("[DRY RUN] 不执行实际转账")
        return True
    
    nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(OLD_WALLET))
    tx = {
        'nonce': nonce,
        'to': Web3.to_checksum_address(EOA_WALLET),
        'value': amount_wei,
        'gas': gas_estimate,
        'gasPrice': w3.to_wei(50, 'gwei'),  # 50 gwei
        'chainId': 137,
    }
    
    signed = old_account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"✅ POL 转账已发送: {tx_hash.hex()}")
    
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    print(f"✅ POL 转账确认: status={receipt['status']}, gas={receipt['gasUsed']}")
    return receipt['status'] == 1


def step2_swap_native_usdc_to_usdce():
    """Step 2: 在老钱包中将 Native USDC 换成 USDC.e (通过 QuickSwap)"""
    print("\n" + "=" * 60)
    print("Step 2: Native USDC → USDC.e (QuickSwap swap)")
    print("=" * 60)
    
    # Check Native USDC balance
    native_contract = w3.eth.contract(
        address=Web3.to_checksum_address(USDC_NATIVE),
        abi=ERC20_ABI
    )
    raw_balance = native_contract.functions.balanceOf(
        Web3.to_checksum_address(OLD_WALLET)
    ).call()
    usdc_native_decimals = native_contract.functions.decimals().call()
    usdc_balance = raw_balance / (10 ** usdc_native_decimals)
    
    print(f"老钱包 Native USDC: {usdc_balance:.6f}")
    
    if usdc_balance < 0.5:
        print("⚠️ Native USDC 余额不足，跳过交换")
        return True
    
    # 保留少量 USDC 不换 (0.01 USDC buffer)
    swap_amount_raw = raw_balance - (10 ** usdc_native_decimals) // 100  # 0.01 USDC buffer
    swap_amount = swap_amount_raw / (10 ** usdc_native_decimals)
    
    print(f"计划交换: {swap_amount:.6f} Native USDC → USDC.e")
    
    if DRY_RUN:
        print("[DRY RUN] 不执行实际交换")
        # Show expected output
        router = w3.eth.contract(
            address=Web3.to_checksum_address(QUICKSWAP_ROUTER),
            abi=ROUTER_ABI
        )
        try:
            amounts_out = router.functions.getAmountsOut(
                swap_amount_raw,
                [Web3.to_checksum_address(USDC_NATIVE), Web3.to_checksum_address(USDC_E)]
            ).call()
            expected_out = amounts_out[1] / (10 ** 6)  # USDC.e has 6 decimals
            print(f"预估输出: {expected_out:.6f} USDC.e")
        except Exception as e:
            print(f"无法预估输出: {e}")
        return True
    
    # 1. Approve Native USDC to QuickSwap Router
    print("Approving Native USDC for QuickSwap Router...")
    approve_tx = native_contract.functions.approve(
        Web3.to_checksum_address(QUICKSWAP_ROUTER),
        2**256 - 1  # Infinite approval
    ).build_transaction({
        'from': Web3.to_checksum_address(OLD_WALLET),
        'nonce': w3.eth.get_transaction_count(Web3.to_checksum_address(OLD_WALLET)),
        'gas': 100000,
        'gasPrice': w3.to_wei(50, 'gwei'),
        'chainId': 137,
    })
    
    signed_approve = old_account.sign_transaction(approve_tx)
    approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
    print(f"Approve TX: {approve_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(approve_hash, timeout=120)
    print(f"Approve confirmed: status={receipt['status']}")
    
    if receipt['status'] != 1:
        print("❌ Approve 失败!")
        return False
    
    # 2. Swap
    print(f"Executing swap: {swap_amount:.6f} Native USDC → USDC.e...")
    
    # Get expected output for slippage
    router = w3.eth.contract(
        address=Web3.to_checksum_address(QUICKSWAP_ROUTER),
        abi=ROUTER_ABI
    )
    
    try:
        amounts_out = router.functions.getAmountsOut(
            swap_amount_raw,
            [Web3.to_checksum_address(USDC_NATIVE), Web3.to_checksum_address(USDC_E)]
        ).call()
        expected_out = amounts_out[1] / (10 ** 6)
        print(f"Expected output: {expected_out:.6f} USDC.e")
        min_out = int(amounts_out[1] * 0.98)  # 2% slippage tolerance
    except Exception as e:
        print(f"Warning: Could not estimate output: {e}")
        min_out = 0  # 0 = any amount (dangerous but works)
    
    deadline = int(time.time()) + 600  # 10 min deadline
    
    swap_tx = router.functions.swapExactTokensForTokensSupportingFeeOnTransferTokens(
        swap_amount_raw,
        min_out,
        [Web3.to_checksum_address(USDC_NATIVE), Web3.to_checksum_address(USDC_E)],
        Web3.to_checksum_address(OLD_WALLET),
        deadline,
    ).build_transaction({
        'from': Web3.to_checksum_address(OLD_WALLET),
        'nonce': w3.eth.get_transaction_count(Web3.to_checksum_address(OLD_WALLET)),
        'gas': 300000,
        'gasPrice': w3.to_wei(50, 'gwei'),
        'chainId': 137,
    })
    
    signed_swap = old_account.sign_transaction(swap_tx)
    swap_hash = w3.eth.send_raw_transaction(signed_swap.raw_transaction)
    print(f"Swap TX: {swap_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(swap_hash, timeout=180)
    print(f"Swap confirmed: status={receipt['status']}, gas={receipt['gasUsed']}")
    
    if receipt['status'] != 1:
        print("❌ Swap 失败!")
        return False
    
    # Check new balance
    time.sleep(3)
    usdce_contract = w3.eth.contract(
        address=Web3.to_checksum_address(USDC_E),
        abi=ERC20_ABI
    )
    new_usdce = usdce_contract.functions.balanceOf(
        Web3.to_checksum_address(OLD_WALLET)
    ).call() / (10 ** 6)
    print(f"✅ Swap 成功! 老钱包 USDC.e 余额: {new_usdce:.6f}")
    
    return True


def step3_transfer_usdce_to_eoa():
    """Step 3: 将老钱包的 USDC.e 转到 EOA 钱包"""
    print("\n" + "=" * 60)
    print("Step 3: USDC.e 转移 → EOA 钱包")
    print("=" * 60)
    
    # Check USDC.e balance on old wallet
    usdce_contract = w3.eth.contract(
        address=Web3.to_checksum_address(USDC_E),
        abi=ERC20_ABI
    )
    raw_balance = usdce_contract.functions.balanceOf(
        Web3.to_checksum_address(OLD_WALLET)
    ).call()
    usdce_balance = raw_balance / (10 ** 6)
    
    print(f"老钱包 USDC.e: {usdce_balance:.6f}")
    
    if usdce_balance < 0.5:
        print("⚠️ USDC.e 余额不足，跳过转账")
        return True
    
    # Leave 0.01 USDC.e as buffer
    transfer_amount = raw_balance - (10 ** 4)  # 0.01 USDC.e buffer
    
    if DRY_RUN:
        print(f"[DRY RUN] 不执行实际转账, 计划转 {transfer_amount / 10**6:.6f} USDC.e")
        return True
    
    # Transfer USDC.e
    nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(OLD_WALLET))
    tx = usdce_contract.functions.transfer(
        Web3.to_checksum_address(EOA_WALLET),
        transfer_amount,
    ).build_transaction({
        'from': Web3.to_checksum_address(OLD_WALLET),
        'nonce': nonce,
        'gas': 100000,
        'gasPrice': w3.to_wei(50, 'gwei'),
        'chainId': 137,
    })
    
    signed = old_account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"✅ USDC.e 转账已发送: {tx_hash.hex()}")
    
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    print(f"✅ USDC.e 转账确认: status={receipt['status']}, gas={receipt['gasUsed']}")
    return receipt['status'] == 1


def step4_approve_usdce_for_polymarket():
    """Step 4: Approve USDC.e for Polymarket Exchange contract"""
    print("\n" + "=" * 60)
    print("Step 4: Approve USDC.e → Polymarket Exchange")
    print("=" * 60)
    
    # Check EOA wallet USDC.e balance
    usdce_contract = w3.eth.contract(
        address=Web3.to_checksum_address(USDC_E),
        abi=ERC20_ABI
    )
    raw_balance = usdce_contract.functions.balanceOf(
        Web3.to_checksum_address(EOA_WALLET)
    ).call()
    usdce_balance = raw_balance / (10 ** 6)
    
    print(f"EOA 钱包 USDC.e: {usdce_balance:.6f}")
    
    if usdce_balance < 0.1:
        print("⚠️ EOA 钱包 USDC.e 余额不足，无法 approve")
        return False
    
    # Check current allowance
    current_allowance = usdce_contract.functions.allowance(
        Web3.to_checksum_address(EOA_WALLET),
        Web3.to_checksum_address(NEG_RISK_EXCHANGE),
    ).call()
    current_allowance_usdce = current_allowance / (10 ** 6)
    print(f"当前 allowance: {current_allowance_usdce:.2f} USDC.e")
    
    if current_allowance >= raw_balance:
        print("✅ Allowance 已足够，无需再次 approve")
        return True
    
    if DRY_RUN:
        print(f"[DRY RUN] 不执行实际 approve, 计划 approve {raw_balance / 10**6:.6f} USDC.e")
        return True
    
    # Infinite approve for Polymarket Exchange
    print("Approving USDC.e for Polymarket NegRisk Exchange...")
    nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(EOA_WALLET))
    
    tx = usdce_contract.functions.approve(
        Web3.to_checksum_address(NEG_RISK_EXCHANGE),
        2**256 - 1,  # Infinite approval
    ).build_transaction({
        'from': Web3.to_checksum_address(EOA_WALLET),
        'nonce': nonce,
        'gas': 100000,
        'gasPrice': w3.to_wei(50, 'gwei'),
        'chainId': 137,
    })
    
    signed = new_account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"✅ Approve TX: {tx_hash.hex()}")
    
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    print(f"✅ Approve 确认: status={receipt['status']}")
    return receipt['status'] == 1


def step5_deposit_to_clob():
    """Step 5: 将 USDC.e 存入 Polymarket CLOB 账户"""
    print("\n" + "=" * 60)
    print("Step 5: Deposit USDC.e → Polymarket CLOB")
    print("=" * 60)
    
    # Check EOA wallet USDC.e balance
    usdce_contract = w3.eth.contract(
        address=Web3.to_checksum_address(USDC_E),
        abi=ERC20_ABI
    )
    raw_balance = usdce_contract.functions.balanceOf(
        Web3.to_checksum_address(EOA_WALLET)
    ).call()
    usdce_balance = raw_balance / (10 ** 6)
    
    print(f"EOA 钱包 USDC.e: {usdce_balance:.6f}")
    
    if usdce_balance < 0.5:
        print("⚠️ USDC.e 余额不足，无法 deposit")
        return False
    
    # Check current allowance
    current_allowance = usdce_contract.functions.allowance(
        Web3.to_checksum_address(EOA_WALLET),
        Web3.to_checksum_address(NEG_RISK_EXCHANGE),
    ).call()
    
    if current_allowance < raw_balance:
        print("❌ Allowance 不足，请先执行 Step 4")
        return False
    
    if DRY_RUN:
        print(f"[DRY RUN] 不执行实际 deposit, 计划存入 {usdce_balance:.6f} USDC.e")
        return True
    
    # Deposit to NegRisk Exchange
    print(f"Depositing {usdce_balance:.6f} USDC.e to Polymarket CLOB...")
    
    exchange_contract = w3.eth.contract(
        address=Web3.to_checksum_address(NEG_RISK_EXCHANGE),
        abi=EXCHANGE_ABI
    )
    
    nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(EOA_WALLET))
    tx = exchange_contract.functions.deposit(
        Web3.to_checksum_address(USDC_E),
        raw_balance,  # Deposit full balance
    ).build_transaction({
        'from': Web3.to_checksum_address(EOA_WALLET),
        'nonce': nonce,
        'gas': 150000,
        'gasPrice': w3.to_wei(50, 'gwei'),
        'chainId': 137,
    })
    
    signed = new_account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"✅ Deposit TX: {tx_hash.hex()}")
    
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    print(f"✅ Deposit 确认: status={receipt['status']}, gas={receipt['gasUsed']}")
    return receipt['status'] == 1


def step6_swap_pol_to_usdce():
    """Step 6 (可选): 将老钱包剩余 POL 换成 USDC.e"""
    print("\n" + "=" * 60)
    print("Step 6: POL → USDC.e (QuickSwap)")
    print("=" * 60)
    
    old_balance = w3.eth.get_balance(Web3.to_checksum_address(OLD_WALLET))
    pol_balance = float(w3.from_wei(old_balance, 'ether'))
    
    # Keep 5 POL for gas
    keep_pol = 5.0
    swap_pol = pol_balance - keep_pol
    
    print(f"老钱包 POL: {pol_balance:.4f}")
    print(f"计划保留: {keep_pol} POL (gas)")
    print(f"计划交换: {swap_pol:.4f} POL → USDC.e")
    
    if swap_pol < 5.0:  # Less than $1 worth
        print("⚠️ 可交换 POL 不足，跳过")
        return True
    
    swap_wei = w3.to_wei(swap_pol, 'ether')
    
    # Get expected output
    router = w3.eth.contract(
        address=Web3.to_checksum_address(QUICKSWAP_ROUTER),
        abi=ROUTER_ABI
    )
    
    try:
        amounts_out = router.functions.getAmountsOut(
            swap_wei,
            [Web3.to_checksum_address(WMATIC), Web3.to_checksum_address(USDC_E)]
        ).call()
        expected_usdce = amounts_out[1] / (10 ** 6)
        print(f"预估输出: {expected_usdce:.6f} USDC.e")
        min_out = int(amounts_out[1] * 0.98)  # 2% slippage
    except Exception as e:
        print(f"Warning: Could not estimate output: {e}")
        min_out = 0
    
    if DRY_RUN:
        print("[DRY RUN] 不执行实际交换")
        return True
    
    # Wrap POL → WMATIC first, then swap
    # Actually, QuickSwap Router has swapExactETHForTokens
    # But it's simpler to use swapExactETHForTokensSupportingFeeOnTransferTokens
    
    # Actually, we need to use the router's swap function for ETH/POL
    # Let's use the router02 ABI with swapExactETHForTokensSupportingFeeOnTransferTokens
    
    ROUTER_ABI_ETH = json.loads('''[
        {"inputs":[{"name":"amountOutMin","type":"uint256"},{"name":"path","type":"address[]"},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactETHForTokensSupportingFeeOnTransferTokens","outputs":[],"type":"function","stateMutability":"payable"},
        {"inputs":[{"name":"amountIn","type":"uint256"},{"name":"path","type":"address[]"}],"name":"getAmountsOut","outputs":[{"name":"amounts","type":"uint256[]"}],"type":"function"}
    ]''')
    
    router_eth = w3.eth.contract(
        address=Web3.to_checksum_address(QUICKSWAP_ROUTER),
        abi=ROUTER_ABI_ETH
    )
    
    deadline = int(time.time()) + 600
    
    tx = router_eth.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
        min_out,
        [Web3.to_checksum_address(WMATIC), Web3.to_checksum_address(USDC_E)],
        Web3.to_checksum_address(OLD_WALLET),
        deadline,
    ).build_transaction({
        'from': Web3.to_checksum_address(OLD_WALLET),
        'value': swap_wei,
        'nonce': w3.eth.get_transaction_count(Web3.to_checksum_address(OLD_WALLET)),
        'gas': 300000,
        'gasPrice': w3.to_wei(50, 'gwei'),
        'chainId': 137,
    })
    
    signed = old_account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"✅ POL→USDC.e Swap TX: {tx_hash.hex()}")
    
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    print(f"✅ Swap 确认: status={receipt['status']}, gas={receipt['gasUsed']}")
    
    return receipt['status'] == 1


def main():
    print("🔧 Polymarket 资金迁移工具")
    print(f"网络: Polygon (Chain ID: 137)")
    print(f"RPC: {RPC_URL[:50]}...")
    print(f"老钱包: {OLD_WALLET}")
    print(f"EOA 钱包: {EOA_WALLET}")
    print(f"存款钱包: {DEPOSIT_WALLET}")
    print(f"DRY RUN: {DRY_RUN}")
    print()
    
    # Check connection
    if not w3.is_connected():
        print("❌ 无法连接到 Polygon RPC!")
        sys.exit(1)
    print(f"✅ RPC 已连接, Block: {w3.eth.block_number}")
    
    # Initial balances
    check_balances()
    
    # Parse step argument
    step_arg = None
    for i, arg in enumerate(sys.argv):
        if arg == '--step' and i + 1 < len(sys.argv):
            step_arg = int(sys.argv[i + 1])
    
    if step_arg:
        steps = {
            1: step1_transfer_pol_for_gas,
            2: step2_swap_native_usdc_to_usdce,
            3: step3_transfer_usdce_to_eoa,
            4: step4_approve_usdce_for_polymarket,
            5: step5_deposit_to_clob,
            6: step6_swap_pol_to_usdce,
        }
        if step_arg in steps:
            result = steps[step_arg]()
            print(f"\nStep {step_arg} 结果: {'✅ 成功' if result else '❌ 失败'}")
        else:
            print(f"未知步骤: {step_arg}")
        check_balances()
        return
    
    # Auto mode: execute all steps
    print("\n🚀 执行所有步骤...")
    
    steps = [
        ("Step 1: 转移 POL (gas)", step1_transfer_pol_for_gas),
        ("Step 2: Native USDC → USDC.e", step2_swap_native_usdc_to_usdce),
        ("Step 3: USDC.e → EOA", step3_transfer_usdce_to_eoa),
        ("Step 4: Approve USDC.e", step4_approve_usdce_for_polymarket),
        ("Step 5: Deposit → CLOB", step5_deposit_to_clob),
        ("Step 6: POL → USDC.e (可选)", step6_swap_pol_to_usdce),
    ]
    
    for step_name, step_fn in steps:
        print(f"\n>>> 执行: {step_name}")
        try:
            result = step_fn()
            if not result:
                print(f"❌ {step_name} 失败，跳过后续步骤")
                break
        except Exception as e:
            print(f"❌ {step_name} 异常: {e}")
            import traceback
            traceback.print_exc()
            break
    
    # Final balances
    print("\n📈 最终余额:")
    check_balances()


if __name__ == '__main__':
    main()
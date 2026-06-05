"""Quick CLOB collateral balance check."""
import sys
sys.path.insert(0, ".")

from core.config import CONFIG
from core.clob_client import get_clob_client, ClobClientManager
from py_clob_client_v2.clob_types import BalanceAllowanceParams, AssetType

ClobClientManager.reset()
client = get_clob_client()
params = BalanceAllowanceParams(
    asset_type=AssetType.COLLATERAL,
    signature_type=CONFIG.wallet.signature_type,
)
client.update_balance_allowance(params)
bal = client.get_balance_allowance(params)
balance_usd = int(bal.get("balance", "0")) / 1e6
print(f"CLOB_BALANCE_USDC={balance_usd:.2f}")
print(f"MAX_TRADE_SIZE={CONFIG.trading.max_trade_size}")
print(f"MIN_PROFIT_THRESHOLD={CONFIG.trading.min_profit_threshold}")

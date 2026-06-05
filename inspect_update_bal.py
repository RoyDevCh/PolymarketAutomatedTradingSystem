import inspect
from py_clob_client_v2.client import ClobClient
print(inspect.getsource(ClobClient.update_balance_allowance))
print("\n--- BalanceAllowanceParams ---")
from py_clob_client_v2.clob_types import BalanceAllowanceParams, AssetType
print(inspect.signature(BalanceAllowanceParams.__init__))
print("AssetType:", list(AssetType))

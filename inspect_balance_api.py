import inspect
from py_clob_client_v2.client import ClobClient
print(inspect.getsource(ClobClient.get_balance_allowance))
print("\n--- update ---")
print(inspect.getsource(ClobClient.update_balance_allowance))

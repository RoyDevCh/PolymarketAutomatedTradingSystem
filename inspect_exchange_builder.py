import inspect
from py_clob_client_v2.order_builder.exchange_order_builder_v2 import ExchangeOrderBuilderV2
src = inspect.getsource(ExchangeOrderBuilderV2)
for line in src.splitlines():
    if any(k in line.lower() for k in ["deposit", "pusd", "collateral", "wallet", "approve"]):
        print(line.rstrip())

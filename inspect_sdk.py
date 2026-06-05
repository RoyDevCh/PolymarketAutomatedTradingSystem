import inspect
from py_clob_client_v2.client import ClobClient
methods = [m for m in dir(ClobClient) if "balance" in m.lower() or "allow" in m.lower() or "deposit" in m.lower() or "sync" in m.lower()]
print("ClobClient methods:", methods)
for m in methods:
    try:
        print(f"\n=== {m} ===")
        print(inspect.signature(getattr(ClobClient, m)))
    except: pass

try:
    from py_clob_client_v2.config import get_contract_config
    c = get_contract_config(137)
    print("\nContract config:", c)
except Exception as e:
    print("config error:", e)

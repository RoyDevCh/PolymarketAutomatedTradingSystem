import py_clob_client_v2.endpoints as ep
import inspect
for name in dir(ep):
    if not name.startswith("_"):
        print(f"{name} = {getattr(ep, name)}")

"""Inspect V2 OrderBuilder maker/signer logic."""
import inspect
from py_clob_client_v2.order_builder.builder import OrderBuilder

src = inspect.getsource(OrderBuilder)
lines = src.split("\n")
for i, line in enumerate(lines):
    if any(k in line.lower() for k in ["maker", "signer", "funder", "signature_type", "poly_1271", "poly_network", "get_maker"]):
        print(f"L{i}: {line.rstrip()}")

print("\n=== build_order (V2 section) ===")
in_v2 = False
for i, line in enumerate(lines):
    if "version == 2" in line or "OrderDataV2" in line:
        in_v2 = True
    if in_v2:
        print(f"L{i}: {line.rstrip()}")
        if i > 0 and in_v2 and line.strip() == "" and "OrderDataV2" in "".join(lines[max(0,i-5):i]):
            pass
    if in_v2 and "return" in line and "SignedOrderV2" in line:
        break

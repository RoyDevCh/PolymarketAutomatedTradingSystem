"""Check how the V2 builder handles signature_type and funder."""
import inspect
from py_clob_client_v2.order_builder.builder import OrderBuilder

src = inspect.getsource(OrderBuilder)
# Find lines that mention funder or signature
funder_lines = []
for i, line in enumerate(src.split('\n')):
    if 'funder' in line.lower() or 'signature' in line.lower() or 'maker' in line.lower():
        funder_lines.append(f"L{i}: {line.rstrip()}")

print("OrderBuilder funder/signature/maker references:")
for line in funder_lines[:30]:
    print(line)

# Also check Signer class
print("\n=== Signer ===")
try:
    from py_clob_client_v2.order_builder.signer import Signer
    sign_src = inspect.getsource(Signer)
    for i, line in enumerate(sign_src.split('\n')):
        if 'funder' in line or 'signature_type' in line or 'POLY' in line:
            print(f"  L{i}: {line.rstrip()}")
except Exception as e:
    print(f"Error: {e}")

# Check what sig_type=2 and sig_type=3 do differently
print("\n=== PKSigner ===")
try:
    from py_clob_client_v2.order_builder.pk_signer import PKSigner
    pk_src = inspect.getsource(PKSigner)
    for i, line in enumerate(pk_src.split('\n')):
        if 'sig' in line.lower() or 'funder' in line.lower() or 'type' in line.lower():
            print(f"  L{i}: {line.rstrip()}")
except Exception as e:
    print(f"PKSigner not found: {e}")

# Check the builder init
print("\n=== OrderBuilder.__init__ ===")
init_src = inspect.getsource(OrderBuilder.__init__)
print(init_src)

# Check build_order method
print("\n=== OrderBuilder.build_order ===")
build_src = inspect.getsource(OrderBuilder.build_order)
# Only print first 50 lines
for i, line in enumerate(build_src.split('\n')[:50]):
    print(f"  {line}")
"""Check CLOB V2 order signing mechanism."""
import inspect
import py_clob_client_v2.client as client

# Check create_order signature
print("=== ClobClient.create_order ===")
try:
    src = inspect.getsource(client.ClobClient.create_order)
    print(src[:2000])
except Exception as e:
    print(f"Error: {e}")

print("\n=== ClobClient.__init__ params ===")
try:
    sig = inspect.signature(client.ClobClient.__init__)
    print(sig)
except Exception as e:
    print(f"Error: {e}")

# Check signature types
print("\n=== Available signature types ===")
try:
    from py_clob_client_v2.clob_types import SignatureType
    for name, value in inspect.getmembers(SignatureType):
        if not name.startswith('_'):
            print(f"  {name} = {value}")
except ImportError:
    print("SignatureType not in clob_types")

# Check SigType enum
try:
    from py_clob_client_v2.clob_types import SigType
    print("\n=== SigType ===")
    for name, value in inspect.getmembers(SigType):
        if not name.startswith('_'):
            print(f"  {name} = {value}")
except ImportError:
    pass

# Check order builder
print("\n=== Order builder ===")
try:
    from py_clob_client_v2.order_builder.builder import OrderBuilder
    src = inspect.getsource(OrderBuilder.build_v2_order)
    print(src[:2000])
except Exception as e:
    print(f"Error: {e}")

# Check what funder does
print("\n=== ClobClient source (funder handling) ===")
try:
    src = inspect.getsource(client.ClobClient)
    # Find funder references
    lines = src.split('\n')
    for i, line in enumerate(lines):
        if 'funder' in line.lower() or 'signature_type' in line.lower() or 'sig_type' in line.lower():
            print(f"  L{i}: {line.rstrip()}")
except Exception as e:
    print(f"Error: {e}")
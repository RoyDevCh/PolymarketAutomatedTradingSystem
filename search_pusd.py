import os, inspect, pkgutil
import py_clob_client_v2
import py_builder_relayer_client

# Search for deposit/pusd references in installed packages
for pkg_name in ["py_clob_client_v2", "py_builder_relayer_client"]:
    pkg = __import__(pkg_name)
    pkg_path = pkg.__path__[0]
    print(f"\n=== Searching {pkg_name} ===")
    import pathlib
    for f in pathlib.Path(pkg_path).rglob("*.py"):
        text = f.read_text(errors="ignore")
        for kw in ["pUSD", "deposit", "collateral", "C011a7E1", "mint"]:
            if kw.lower() in text.lower():
                lines = [l.strip() for l in text.splitlines() if kw.lower() in l.lower()]
                if lines:
                    print(f"  {f.name}: {lines[0][:120]}")

# Check relayer client methods
from py_builder_relayer_client.client import RelayClient
methods = [m for m in dir(RelayClient) if not m.startswith("_")]
print(f"\nRelayClient methods: {methods}")

# Check for deploy/deposit methods
for m in methods:
    if "deposit" in m.lower() or "deploy" in m.lower() or "convert" in m.lower():
        print(f"  {m}: {inspect.signature(getattr(RelayClient, m))}")

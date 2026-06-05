import pathlib, inspect
pkg = pathlib.Path("/home/roy/polymarket-arb/venv/lib/python3.14/site-packages/py_builder_relayer_client")
for f in pkg.rglob("*.py"):
    text = f.read_text(errors="ignore")
    if "deposit" in text.lower() or "pusd" in text.lower() or "collateral" in text.lower():
        print(f"\n=== {f.name} ===")
        for line in text.splitlines():
            ll = line.lower()
            if any(k in ll for k in ["deposit", "pusd", "collateral", "mint", "convert", "usdc"]):
                print(f"  {line.rstrip()[:120]}")

from pathlib import Path
p = Path("main.py")
t = p.read_text(encoding="utf-8")
t = t.replace('stats["trades_today"] = "unavailable\'', 'stats["trades_today"] = "unavailable"')
p.write_text(t, encoding="utf-8")
print("ok")

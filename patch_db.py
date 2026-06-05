"""Patch oeg.py to add virtual fill SQLite persistence"""
import pathlib
p = pathlib.Path(r"C:\Users\rjq51\Documents\pi\PolymarketAutomatedTradingSystem\polymarket-arb\core\oeg.py")
content = p.read_text(encoding="utf-8")

old = '''                        self._stats.setdefault("virtual_fills", 0)
                        self._stats["virtual_fills"] += 1
                        if vo["adverse_selection"]:
                            self._stats.setdefault("virtual_adverse_selections", 0)
                            self._stats["virtual_adverse_selections"] += 1
                        expired.append(sig_id)'''

new = '''                        self._stats.setdefault("virtual_fills", 0)
                        self._stats["virtual_fills"] += 1
                        if vo["adverse_selection"]:
                            self._stats.setdefault("virtual_adverse_selections", 0)
                            self._stats["virtual_adverse_selections"] += 1
                        # Persist to SQLite for weekend analysis
                        try:
                            import sqlite3 as _sq
                            from pathlib import Path as _P
                            _db = str(_P(__file__).resolve().parent.parent / "db" / "arbitrage.db")
                            _c = _sq.connect(_db)
                            _c.execute("""CREATE TABLE IF NOT EXISTS virtual_fills (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                signal_id TEXT, condition_id TEXT,
                                bid_yes REAL, bid_no REAL, size REAL,
                                fill_time_ms REAL, adverse_selection INTEGER,
                                profit REAL, created_at TEXT DEFAULT (datetime('now')))""")
                            _c.execute("INSERT INTO virtual_fills (signal_id,condition_id,bid_yes,bid_no,size,fill_time_ms,adverse_selection,profit) VALUES (?,?,?,?,?,?,?,?)",
                                (sig_id, vo.get("condition_id",""), vo["bid_yes"], vo["bid_no"], vo["size"],
                                 (now - vo["placed_at"]) * 1000, 1 if vo["adverse_selection"] else 0, profit))
                            _c.commit()
                            _c.close()
                        except Exception as _dbe:
                            logger.debug("virtual_fill_db_error: %s", _dbe)
                        expired.append(sig_id)'''

content = content.replace(old, new)
p.write_text(content, encoding="utf-8")
print("OK")
from pathlib import Path
p = Path(r"C:\Users\rjq51\Documents\pi\PolymarketAutomatedTradingSystem\polymarket-arb\deploy_breakout.py")
t = p.read_text(encoding="utf-8")
t = t.replace(
    "f\"mkdir -p logs; nohup python main.py --debug > logs/main_debug.log 2>&1 & sleep 2; pgrep -af main.py'\"",
    "f\"source venv/bin/activate; mkdir -p logs; nohup python main.py --debug > logs/main_debug.log 2>&1 & sleep 2; pgrep -af main.py'\"",
)
t = t.replace(
    "f\"python test_probe_trade.py > logs/probe_trade.log 2>&1'\"",
    "f\"source venv/bin/activate; python test_probe_trade.py > logs/probe_trade.log 2>&1'\"",
)
if "venv/bin/pip install" not in t:
    t = t.replace(
        "    sftp.close()\n\n    ssh.exec_command(\"pkill",
        "    sftp.close()\n\n    ssh.exec_command(\n        f\"bash -lc 'cd {REMOTE} && source venv/bin/activate && pip install -q asyncpg structlog'\",\n        timeout=180,\n    )\n\n    ssh.exec_command(\"pkill",
    )
p.write_text(t, encoding="utf-8")
print("fixed venv")

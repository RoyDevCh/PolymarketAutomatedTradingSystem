#!/usr/bin/env python3
"""
Remote deploy script - upload project to server and install dependencies
"""
import paramiko
import os
import sys

HOST = "192.168.3.117"
USER = "roy"
PASS = "kaiyic"
REMOTE_DIR = "/home/roy/polymarket-arb"
VENV_PIP = f"{REMOTE_DIR}/venv/bin/pip"
LOCAL_DIR = os.path.dirname(os.path.abspath(__file__))

FILES_TO_UPLOAD = [
    ".env.example",
    ".gitignore",
    "requirements.txt",
    "main.py",
    "test_phase1.py",
    "test_phase2.py",
    "core/__init__.py",
    "core/config.py",
    "core/models.py",
    "core/clob_client.py",
    "core/mdg.py",
    "core/spe.py",
    "core/oeg.py",
    "core/rmc.py",
    "db/schema.sql",
    "deploy/polymarket-arb.service",
    "deploy/deploy.sh",
]


def log(msg):
    print(msg, flush=True)


def main():
    log(f"[1/5] Connecting to {HOST}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASS, timeout=10)
    log("[1/5] SSH connected OK")

    # Create dirs
    log("[2/5] Creating directories...")
    for d in ["core", "db", "deploy", "logs"]:
        ssh.exec_command(f"mkdir -p {REMOTE_DIR}/{d}")
    log("[2/5] Done")

    # Upload files via SFTP
    log("[3/5] Uploading project files...")
    sftp = ssh.open_sftp()

    for rel_path in FILES_TO_UPLOAD:
        local_path = os.path.join(LOCAL_DIR, rel_path)
        remote_path = f"{REMOTE_DIR}/{rel_path}"
        try:
            sftp.put(local_path, remote_path)
            log(f"  + {rel_path}")
        except Exception as e:
            log(f"  x {rel_path}: {e}")

    # Copy .env.example -> .env
    try:
        sftp.put(
            os.path.join(LOCAL_DIR, ".env.example"),
            f"{REMOTE_DIR}/.env"
        )
        log(f"  + .env (copied from .env.example)")
    except Exception as e:
        log(f"  x .env: {e}")

    sftp.close()
    log("[3/5] Upload complete")

    # Install Python deps
    log("[4/5] Installing Python dependencies (1-2 min)...")
    stdin, stdout, stderr = ssh.exec_command(
        f"{VENV_PIP} install -r {REMOTE_DIR}/requirements.txt 2>&1 | tail -10",
        timeout=300,
    )
    out = stdout.read().decode().strip()
    log(f"  {out[-500:]}")
    log("[4/5] Dependencies installed")

    # Verify
    log("[5/5] Verifying module imports...")
    stdin, stdout, stderr = ssh.exec_command(
        f"cd {REMOTE_DIR} && {REMOTE_DIR}/venv/bin/python -c \""
        "from core.models import TradeSignal, Side; "
        "from core.config import CONFIG; "
        "from core.mdg import MarketDataGateway; "
        "from core.spe import StrategyPricingEngine; "
        "from core.oeg import OrderExecutionGateway, FillTracker, OrderTracker; "
        "from core.rmc import RiskManagementCenter; "
        "print('ALL_MODULES_OK');"
        "\""
    )
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    log(f"  stdout: {out}")
    if err:
        log(f"  stderr: {err[-300:]}")

    # Show file listing
    log("\n=== Remote file listing ===")
    stdin, stdout, stderr = ssh.exec_command(
        f"find {REMOTE_DIR} -type f -not -path '*/venv/*' -not -path '*/__pycache__/*' | sort"
    )
    print(stdout.read().decode().strip())

    ssh.close()

    log("\n============================================")
    log("  DEPLOY COMPLETE")
    log("============================================")
    log(f"\nNext steps:")
    log(f"  ssh roy@192.168.3.117")
    log(f"  nano {REMOTE_DIR}/.env")
    log(f"  cd {REMOTE_DIR} && source venv/bin/activate")
    log(f"  python test_phase1.py")
    log(f"  python test_phase2.py --duration 5")


if __name__ == "__main__":
    main()
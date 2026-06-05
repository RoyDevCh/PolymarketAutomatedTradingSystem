"""Update remote .env with Polymarket website API credentials."""
import sys
import paramiko

HOST = "192.168.3.117"
USER = "roy"
PASS = "kaiyic"
REMOTE_ENV = "/home/roy/polymarket-arb/.env"

# Polymarket website credentials (user provided)
PM_API_KEY = "019e95bf-c366-7511-8930-284b2ca5239f"
PM_API_ADDRESS = "0x6b1fda796ffdd756d06cf20ce43f3c8a172e60ee"
DEPOSIT_WALLET = "0xAe886C5740F6614e0300BC2AF95e730f150685Ff"

# Secret/passphrase from command line args
if len(sys.argv) < 3:
    print("Usage: python update_pm_creds.py <API_SECRET> <API_PASSPHRASE>")
    print("Get these from Polymarket website API settings page")
    sys.exit(1)

api_secret = sys.argv[1]
api_passphrase = sys.argv[2]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=10)
sftp = ssh.open_sftp()

with sftp.open(REMOTE_ENV, "r") as f:
    lines = f.read().decode().splitlines()

updates = {
    "API_KEY": PM_API_KEY,
    "API_SECRET": api_secret,
    "API_PASSPHRASE": api_passphrase,
    "PM_API_ADDRESS": PM_API_ADDRESS,
    "DEPOSIT_WALLET": DEPOSIT_WALLET,
    "SIGNATURE_TYPE": "2",
    "WALLET_ADDRESS": PM_API_ADDRESS,
}

new_lines = []
done = set()
for line in lines:
    stripped = line.strip()
    if stripped and not stripped.startswith("#") and "=" in stripped:
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            done.add(key)
            continue
    new_lines.append(line)

for key, val in updates.items():
    if key not in done:
        new_lines.append(f"{key}={val}")

with sftp.open(REMOTE_ENV, "w") as f:
    f.write("\n".join(new_lines) + "\n")

sftp.close()
print("Updated remote .env:")
for k in updates:
    v = updates[k]
    masked = v[:8] + "..." if len(v) > 12 else v
    print(f"  {k}={masked}")

# Run test
stdin, stdout, stderr = ssh.exec_command(
    "curl -s -X PUT http://127.0.0.1:9090/proxies/Polymarket "
    "-H 'Content-Type:application/json' -d '{\"name\": \"JP-01\"}'",
    timeout=5,
)
stdin, stdout, stderr = ssh.exec_command(
    "cd /home/roy/polymarket-arb && source venv/bin/activate && source ~/.proxyrc "
    "&& timeout 60 python3 test_pm_api_v7.py 2>&1",
    timeout=70,
)
out = stdout.read().decode("utf-8", errors="replace")
for line in out.split("\n"):
    if line.strip():
        print(line.encode("ascii", "replace").decode("ascii")[:250])

ssh.close()

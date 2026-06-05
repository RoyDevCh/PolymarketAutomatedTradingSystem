"""Update remote .env with correct V2 config (sig_type=3 + derived creds)."""
import paramiko

# Derived from L1 on remote server (sig_type=2, funder=deposit)
API_KEY = "5f41c859-b253-6d89-bfa0-2b2b8454153a"
API_SECRET = "u9fAElPwcp6iiwN1-qwdv-_nFj7T07eph5vCLW91a4Q="
API_PASSPHRASE = "bb7c52eb4cd968358f342b144cb188fe2de32001e91aaad4a0b0f6a4c51d16bf"

UPDATES = {
    "API_KEY": API_KEY,
    "API_SECRET": API_SECRET,
    "API_PASSPHRASE": API_PASSPHRASE,
    "DEPOSIT_WALLET": "0x181242c978fb34c26068f8B154126F8Ea745C88B",
    "WALLET_ADDRESS": "0xE56A44444F55aD30C87235f7C94786509881Da3A",
    "SIGNATURE_TYPE": "3",
    "BUILDER_CODE": "0x5c126b216752e083ad7febf83647a843b1291002f715a37eea5e5a7c0cc82374",
    "BUILDER_API_KEY": "019e9600-c047-744c-aa20-eb6fc74eb3ce",
    "BUILDER_SECRET": "cFtaH4khfG71v4Hjoml_BmDgAzhio2JwUp2Xg9UOq7A=",
    "BUILDER_PASSPHRASE": "993c56bb068bcbe3b249194ee8cbbbea33b4d96cfcd040a52935ec9934579c04",
}

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.3.117", username="roy", password="kaiyic", timeout=10)
sftp = ssh.open_sftp()

env_path = "/home/roy/polymarket-arb/.env"
with sftp.open(env_path, "r") as f:
    lines = f.read().decode().splitlines()

existing_keys = set()
new_lines = []
for line in lines:
    key = line.split("=", 1)[0].strip() if "=" in line and not line.startswith("#") else None
    if key in UPDATES:
        new_lines.append(f"{key}={UPDATES[key]}")
        existing_keys.add(key)
    else:
        new_lines.append(line)

for key, val in UPDATES.items():
    if key not in existing_keys:
        new_lines.append(f"{key}={val}")

with sftp.open(env_path, "w") as f:
    f.write("\n".join(new_lines) + "\n")

print("Updated .env with V2 config (sig_type=3)")
for k, v in UPDATES.items():
    print(f"  {k}={v[:40]}..." if len(v) > 40 else f"  {k}={v}")

sftp.close()
ssh.close()

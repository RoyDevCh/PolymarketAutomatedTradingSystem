"""Check remote .env keys (no secret values)."""
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.3.117", username="roy", password="kaiyic", timeout=10)

stdin, stdout, stderr = ssh.exec_command(
    "cd /home/roy/polymarket-arb && grep -E '^(API_|PM_|DEPOSIT|WALLET|PRIVATE)' .env | sed 's/=.*/=***/' 2>&1",
    timeout=10,
)
print(stdout.read().decode())
ssh.close()

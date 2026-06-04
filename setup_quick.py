"""
一条命令配置所有凭证 + 自动验证

用法:
  python setup_quick.py --key 0x你的私钥

脚本会自动:
1. 从私钥推导 Polymarket API 密钥
2. 生成 .env 文件
3. 上传到远程服务器
4. 运行所有验证测试

如果 API 密钥获取失败, 需要手动提供:
  python setup_quick.py --key 0x私钥 --apikey KEY --apisecret SECRET --apipass PASS
"""

import os
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

def run(cmd, **kw):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)
    return r.stdout.strip(), r.stderr.strip(), r.returncode

def main():
    import argparse
    parser = argparse.ArgumentParser(description="一键配置 + 验证")
    parser.add_argument("--key", required=True, help="钱包私钥 (0x开头)")
    parser.add_argument("--apikey", default="", help="Polymarket API Key (可选, 自动获取)")
    parser.add_argument("--apisecret", default="", help="Polymarket API Secret (可选)")
    parser.add_argument("--apipass", default="", help="Polymarket API Passphrase (可选)")
    parser.add_argument("--rpc", default="", help="Alchemy RPC URL (可选, 默认公共节点)")
    parser.add_argument("--no-upload", action="store_true", help="不上传到远程服务器")
    args = parser.parse_args()

    private_key = args.key.strip()
    if private_key.startswith("0x") or len(private_key) == 64:
        if not private_key.startswith("0x"):
            private_key = "0x" + private_key
    else:
        print("[ERROR] 私钥格式无效")
        sys.exit(1)

    # 推导钱包地址
    try:
        from eth_account import Account
        acct = Account.from_key(private_key)
        address = acct.address
        print(f"[OK] 钱包地址: {address}")
    except ImportError:
        print("[INFO] 安装 eth-account...")
        subprocess.run("pip install eth-account", shell=True)
        from eth_account import Account
        acct = Account.from_key(private_key)
        address = acct.address
        print(f"[OK] 钱包地址: {address}")

    # 获取 API 密钥
    api_key = args.apikey
    api_secret = args.apisecret
    api_passphrase = args.apipass

    if not all([api_key, api_secret, api_passphrase]):
        print("\n[1/2] 正在从 Polymarket 获取 API 密钥...")
        try:
            from py_clob_client.client import ClobClient
            client = ClobClient(
                host="https://clob.polymarket.com",
                key=private_key,
                chain_id=137,
            )
            # 先尝试 derive (已有密钥)
            try:
                creds = client.derive_api_key()
                api_key = creds.api_key
                api_secret = creds.api_secret
                api_passphrase = creds.api_passphrase
                print(f"[OK] 已有 API 密钥: {api_key[:12]}...")
            except Exception:
                # 再尝试 create
                creds = client.create_api_key()
                api_key = creds.api_key
                api_secret = creds.api_secret
                api_passphrase = creds.api_passphrase
                print(f"[OK] 新建 API 密钥: {api_key[:12]}...")
        except Exception as e:
            print(f"[WARN] 自动获取失败: {e}")
            print("[INFO] 请先在 https://polymarket.com 用此钱包地址登录注册")
            print("[INFO] 然后重新运行此脚本, 或手动提供 --apikey --apisecret --apipass")
            if not all([api_key, api_secret, api_passphrase]):
                print("\n手动获取方式:")
                print("  python -c \"")
                print("  from py_clob_client.client import ClobClient")
                print(f"  c = ClobClient(host='https://clob.polymarket.com', key='{private_key[:10]}...', chain_id=137)")
                print("  print(c.create_api_key())")
                print("  \"")
                sys.exit(1)

    # RPC URL
    rpc_url = args.rpc or "https://polygon-rpc.com"
    if "polygon-rpc.com" in rpc_url:
        print("[WARN] 使用公共 RPC 节点, 建议配置 Alchemy 专属节点")
        print("       免费 Alchemy: https://dashboard.alchemy.com/signup")

    # 写入 .env
    print(f"\n[2/2] 写入 .env 文件...")
    env_path = Path(__file__).parent / ".env"

    lines = [
        "# Polymarket 自动套利系统 - 环境变量",
        "# ⚠️ 此文件包含私钥, 绝对不要提交到 Git!",
        "",
        "# L1 钱包私钥",
        f"PRIVATE_KEY={private_key}",
        "",
        "# L2 Polymarket API 凭证",
        f"API_KEY={api_key}",
        f"API_SECRET={api_secret}",
        f"API_PASSPHRASE={api_passphrase}",
        "",
        "# Polygon RPC 节点",
        f"RPC_URL={rpc_url}",
        "",
        "# 交易参数 (Phase 3 金丝雀: 每笔 $2 上限)",
        "MAX_TRADE_SIZE=2.0",
        "MIN_PROFIT_THRESHOLD=0.005",
        "MAX_SLIPPAGE_PCT=0.5",
        "",
        "# 市场过滤",
        "GAMMA_MIN_VOLUME=1.0",
        "GAMMA_MIN_LIQUIDITY=1.0",
        "",
        "# 风控参数",
        "CONSECUTIVE_FAIL_LIMIT=3",
        "CIRCUIT_BREAKER_COOLDOWN=900",
        "",
        "# Gamma API",
        "GAMMA_API_URL=https://gamma-api.polymarket.com",
        "",
        "# CLOB API",
        "CLOB_API_URL=https://clob.polymarket.com",
        "CLOB_WS_MARKET_URL=wss://ws-subscriptions-clob.polymarket.com/ws/market",
        "CLOB_WS_USER_URL=wss://ws-subscriptions-clob.polymarket.com/ws/user",
    ]

    env_path.write_text("\n".join(lines))
    print(f"[OK] 已写入 {env_path}")

    # 配置摘要
    print(f"\n{'='*50}")
    print(f"  配置摘要")
    print(f"{'='*50}")
    print(f"  钱包地址:  {address}")
    print(f"  PRIVATE:   {private_key[:8]}...{private_key[-4:]}")
    print(f"  API_KEY:   {api_key[:12]}...")
    print(f"  API_SEC:   {api_secret[:8]}...")
    print(f"  API_PASS:  {api_passphrase[:8]}...")
    print(f"  RPC_URL:   {rpc_url[:45]}...")
    print(f"{'='*50}")

    # 上传到远程服务器
    if not args.no_upload:
        print(f"\n[3/3] 上传到远程服务器 192.168.3.117...")
        try:
            import paramiko
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect('192.168.3.117', username='roy', password='kaiyic', timeout=10)
            sftp = ssh.open_sftp()
            sftp.put(str(env_path), '/home/roy/polymarket-arb/.env')
            sftp.close()

            # 同步代码
            for f in ['core/clob_client.py', 'core/oeg.py', 'core/spe.py', 'core/rmc.py',
                       'core/config.py', 'core/mdg.py', 'core/models.py', 'main.py',
                       'test_phase2_5.py', 'test_phase2_v2.py', 'setup_credentials.py']:
                local = str(Path(__file__).parent / f)
                remote = f'/home/roy/polymarket-arb/{f}'
                try:
                    sftp.put(local, remote)
                except FileNotFoundError:
                    pass

            print(f"[OK] 已上传到远程服务器")

            # 验证
            print(f"\n  正在远程验证...")
            stdin, stdout, stderr = ssh.exec_command(
                'cd /home/roy/polymarket-arb && source venv/bin/activate && '
                'pip install eth-account -q 2>/dev/null; '
                'python -c "from core.config import CONFIG; '
                'print(f\'  PRIVATE_KEY: {CONFIG.wallet.private_key[:8]}...\'); '
                'print(f\'  API_KEY: {CONFIG.clob.api_key[:12]}...\'); '
                'print(f\'  RPC_URL: {CONFIG.wallet.rpc_url[:40]}...\'); '
                'print(f\'  Chain: Polygon Mainnet (137)\')" 2>&1',
                timeout=15
            )
            out = stdout.read().decode('utf-8', errors='replace').strip()
            # Filter out pip noise
            for line in out.split('\n'):
                line = line.strip()
                if any(k in line for k in ['PRIVATE', 'API_KEY', 'RPC_URL', 'Chain', 'OK', 'ERROR', 'WARN']):
                    print(f"  {line}")

            ssh.close()
        except Exception as e:
            print(f"[WARN] 上传失败: {e}")
            print(f"  请手动上传: scp .env roy@192.168.3.117:polymarket-arb/.env")

    print(f"\n{'='*50}")
    print(f"  下一步")
    print(f"{'='*50}")
    print(f"  1. 向钱包地址转入 ~0.5 MATIC + 100 USDC")
    print(f"     地址: {address}")
    print(f"  2. 在远程服务器运行测试:")
    print(f"     ssh roy@192.168.3.117")
    print(f"     cd ~/polymarket-arb && source venv/bin/activate && source ~/.proxyrc")
    print(f"     python test_phase2_5.py --all")
    print(f"{'='*50}")

if __name__ == "__main__":
    main()
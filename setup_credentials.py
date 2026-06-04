"""
Polymarket 凭证配置向导

一键获取所有 Phase 3 所需凭证:
  1. PRIVATE_KEY  → 创建新的隔离钱包
  2. API_KEY/SECRET/PASSPHRASE → Polymarket CLOB API 密钥
  3. RPC_URL → Alchemy/QuickNode Polygon 节点

使用方式:
  python setup_credentials.py          # 交互式向导
  python setup_credentials.py --check  # 检查现有 .env 配置

前置条件:
  - MetaMask 或其他 Web3 钱包
  - 少量 MATIC (~0.5 MATIC 用于 gas)
  - Alchemy 或 QuickNode 账户 (免费层即可)
"""

import os
import sys
from pathlib import Path

# 确保项目根目录在路径中
sys.path.insert(0, str(Path(__file__).parent))


def print_header():
    print("=" * 70)
    print("  Polymarket 自动套利系统 - 凭证配置向导")
    print("=" * 70)
    print()


def print_step(step_num, title, description):
    print(f"\n{'─' * 70}")
    print(f"  步骤 {step_num}: {title}")
    print(f"{'─' * 70}")
    print(f"  {description}")
    print()


def check_env():
    """检查现有 .env 配置"""
    env_path = Path(__file__).parent / ".env"
    
    if not env_path.exists():
        return None
    
    config = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val:
                config[key] = val
    
    return config


def validate_private_key(key: str) -> bool:
    """验证私钥格式"""
    key = key.strip()
    if key.startswith("0x"):
        key = key[2:]
    return len(key) == 64 and all(c in "0123456789abcdefABCDEF" for c in key)


def derive_address_from_key(key: str) -> str:
    """从私钥推导地址 (仅用于显示, 不发送交易)"""
    try:
        from eth_account import Account
        acct = Account.from_key(key if key.startswith("0x") else f"0x{key}")
        return acct.address
    except ImportError:
        return "(安装 eth-account 可显示地址)"


def main():
    print_header()
    
    # 检查现有配置
    config = check_env()
    env_path = Path(__file__).parent / ".env"
    env_example_path = Path(__file__).parent / ".env.example"
    
    if config:
        print("  [INFO] 检测到已有 .env 配置:")
        masked = {}
        for k, v in config.items():
            if k in ("PRIVATE_KEY", "API_KEY", "API_SECRET", "API_PASSPHRASE"):
                masked[k] = v[:6] + "..." + v[-4:] if len(v) > 10 else "***"
            elif k == "RPC_URL" and "v2/" in v:
                masked[k] = v[:40] + "..." + v[-8:]
            else:
                masked[k] = v
        for k, v in masked.items():
            print(f"    {k} = {v}")
        
        print()
        action = input("  要重新配置吗? (y/N): ").strip().lower()
        if action != "y":
            print("\n  保留现有配置。如需修改, 直接编辑 .env 文件。")
            return
    
    # ================================================================
    # Step 1: PRIVATE_KEY
    # ================================================================
    print_step(1, "创建隔离钱包 (PRIVATE_KEY)",
        """隔离原则: 你的 Polymarket 套利钱包应该是一个全新的、独立的钱包。
        
  ⚠️  绝对不要使用你的主钱包! 套利机器人可能产生大量链上交易,
  如果密钥泄露或出现 bug, 仅损失套利资金, 不影响主资产。

  获取方式:
  1. 打开 MetaMask → 创建新钱包 (或新账户)
  2. 切换到 Polygon 网络
  3. 向这个地址转入少量 MATIC (~0.5 MATIC 用于 gas)
  4. 导出私钥: MetaMask → 账户详情 → 导出私钥
  5. 将私钥粘贴到下方""")

    private_key = input("\n  请粘贴_PRIVATE_KEY (0x开头或纯hex): ").strip()
    
    if not private_key:
        print("  [ERROR] PRIVATE_KEY 不能为空")
        return
    
    if private_key.startswith("0x"):
        private_key = "0x" + private_key[2:]
    else:
        private_key = "0x" + private_key
    
    if not validate_private_key(private_key):
        print(f"  [ERROR] 私钥格式无效 (应为64位hex, 当前{len(private_key)-2}位)")
        return
    
    address = derive_address_from_key(private_key)
    print(f"\n  [OK] 钱包地址: {address}")
    print(f"  [OK] 请向此地址转入少量 MATIC (Polygon gas fee)")
    
    # ================================================================
    # Step 2: API_KEY / API_SECRET / API_PASSPHRASE
    # ================================================================
    print_step(2, "获取 Polymarket CLOB API 密钥",
        """Polymarket 使用两级认证系统:
  
  Level 1 (L1): 私钥签名 → 用于 create_api_key / derive_api_key
  Level 2 (L2): API_KEY + SECRET + PASSPHRASE → 用于下单

  你的私钥就是 L1 认证。L2 凭证需要通过 L1 认证从 Polymarket 获取。
  
  获取方式:
  选项 A: 自动获取 (推荐) → 按回车键, 脚本自动调用 Polymarket API
  选项 B: 手动获取 → 在 Python REPL 中操作""")

    auto = input("\n  自动获取 API 凭证? (Y/n): ").strip().lower()
    
    api_key = ""
    api_secret = ""
    api_passphrase = ""
    
    if auto != "n":
        print("\n  正在连接 Polymarket CLOB API...")
        
        try:
            # 加载代理
            proxy_rc = Path.home() / ".proxyrc"
            if proxy_rc.exists():
                for line in proxy_rc.read_text().splitlines():
                    line = line.strip()
                    if line.startswith("export "):
                        line = line[len("export "):]
                    if "=" in line and not line.startswith("#"):
                        key, _, val = line.partition("=")
                        key, val = key.strip(), val.strip()
                        if key.lower().endswith("_proxy") and val:
                            os.environ.setdefault(key, val)
            
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds
            
            # 创建 L1 客户端 (仅私钥, 无 API 凭证)
            client = ClobClient(
                host="https://clob.polymarket.com",
                key=private_key,
                chain_id=137,  # Polygon Mainnet
            )
            
            # 尝试 derive_api_key (如果已有密钥)
            print("  正在检查已有 API 密钥...")
            try:
                creds = client.derive_api_key()
                api_key = creds.api_key
                api_secret = creds.api_secret
                api_passphrase = creds.api_passphrase
                print(f"\n  [OK] 已找到已有 API 密钥:")
                print(f"       API_KEY:         {api_key[:12]}...")
                print(f"       API_SECRET:      {api_secret[:8]}...")
                print(f"       API_PASSPHRASE:  {api_passphrase[:8]}...")
            except Exception as e:
                print(f"  [INFO] 未找到已有密钥 ({type(e).__name__})")
                print("  正在创建新 API 密钥...")
                try:
                    creds = client.create_api_key()
                    api_key = creds.api_key
                    api_secret = creds.api_secret
                    api_passphrase = creds.api_passphrase
                    print(f"\n  [OK] 新 API 密钥已创建:")
                    print(f"       API_KEY:         {api_key[:12]}...")
                    print(f"       API_SECRET:      {api_secret[:8]}...")
                    print(f"       API_PASSPHRASE:  {api_passphrase[:8]}...")
                except Exception as e2:
                    print(f"\n  [WARN] 无法创建 API 密钥: {type(e2).__name__}: {e2}")
                    print("  可能需要先在 https://polymarket.com 注册并登录该钱包地址")
                    print("  然后重新运行此脚本。")
                    print()
                    api_key = input("  API_KEY: ").strip()
                    api_secret = input("  API_SECRET: ").strip()
                    api_passphrase = input("  API_PASSPHRASE: ").strip()
        except Exception as e:
            print(f"\n  [ERROR] 连接 Polymarket API 失败: {type(e).__name__}: {e}")
            print("  请手动输入 API 凭证:")
            print()
            print("  如需手动获取, 请在 Python 中执行:")
            print("    from py_clob_client.client import ClobClient")
            print(f"    client = ClobClient(host='https://clob.polymarket.com', key='{private_key[:10]}...', chain_id=137)")
            print("    creds = client.create_api_key()")
            print("    print(creds.api_key, creds.api_secret, creds.api_passphrase)")
            print()
            api_key = input("  API_KEY: ").strip()
            api_secret = input("  API_SECRET: ").strip()
            api_passphrase = input("  API_PASSPHRASE: ").strip()
    else:
        print("\n  请手动输入 API 凭证:")
        api_key = input("  API_KEY: ").strip()
        api_secret = input("  API_SECRET: ").strip()
        api_passphrase = input("  API_PASSPHRASE: ").strip()
    
    # ================================================================
    # Step 3: RPC_URL
    # ================================================================
    print_step(3, "配置 Polygon RPC 节点 (RPC_URL)",
        """Polymarket 在 Polygon 链上运行, 你需要一个 RPC 节点与链交互。
  
  ⚠️  不要使用公共 RPC (如 https://polygon-rpc.com), 
  公共节点限速严重且不可靠, 会导致交易失败。
  
  推荐选择 (免费层即可):
  
  1. Alchemy (推荐)
     - 注册: https://dashboard.alchemy.com/signup
     - 创建 App → 选择 Polygon
     - 复制 HTTPS URL (格式: https://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY)
  
  2. QuickNode
     - 注册: https://www.quicknode.com/
     - 创建 Endpoint → Polygon Mainnet
     - 复制 HTTP Provider URL""")

    rpc_url = input("\n  RPC_URL: ").strip()
    
    if rpc_url and "polygon-rpc.com" in rpc_url:
        print("\n  [WARN] 检测到公共 RPC 节点! 这将导致交易频繁失败。")
        print("  强烈建议使用 Alchemy 或 QuickNode 的专属节点。")
        confirm = input("  确认继续使用公共节点? (y/N): ").strip().lower()
        if confirm != "y":
            rpc_url = input("  请输入 Alchemy/QuickNode RPC URL: ").strip()
    
    # ================================================================
    # Step 4: 写入 .env
    # ================================================================
    print_step(4, "保存配置到 .env",
        f"配置将写入 {env_path}")
    
    # 读取 .env.example 作为模板
    if env_example_path.exists():
        env_content = env_example_path.read_text()
    else:
        env_content = """# Polymarket 自动套利系统 - 环境变量
"""
    
    # 替换或添加配置
    updates = {
        "PRIVATE_KEY": private_key,
        "API_KEY": api_key,
        "API_SECRET": api_secret,
        "API_PASSPHRASE": api_passphrase,
        "RPC_URL": rpc_url,
    }
    
    lines = env_content.split("\n")
    new_lines = []
    updated_keys = set()
    
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                updated_keys.add(key)
                continue
        new_lines.append(line)
    
    # 添加未在模板中的配置
    for key, val in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}")
    
    # 写入 .env
    env_path.write_text("\n".join(new_lines))
    
    print(f"\n  [OK] 配置已写入 {env_path}")
    print()
    print("  ⚠️  重要提醒:")
    print(f"  1. .env 已在 .gitignore 中, 不会被提交到 Git")
    print(f"  2. 确保钱包地址有足够的 MATIC 用于 gas")
    print(f"  3. 钱包地址: {address}")
    print(f"  4. 建议初始资金: $100 USDC (Polygon)")
    print()
    print("  下一步:")
    print("    ssh roy@192.168.3.117")
    print("    cd ~/polymarket-arb")
    print("    scp .env roy@192.168.3.117:polymarket-arb/.env")
    print("    source venv/bin/activate && source ~/.proxyrc")
    print("    python test_phase2_5.py --all")
    
    # 验证配置
    print("\n  正在验证配置...")
    from dotenv import load_dotenv
    load_dotenv(env_path, override=True)
    
    errors = []
    if not os.getenv("PRIVATE_KEY"):
        errors.append("PRIVATE_KEY 未配置")
    if not os.getenv("API_KEY"):
        errors.append("API_KEY 未配置")
    if not os.getenv("API_SECRET"):
        errors.append("API_SECRET 未配置")
    if not os.getenv("API_PASSPHRASE"):
        errors.append("API_PASSPHRASE 未配置")
    if not os.getenv("RPC_URL") or "polygon-rpc.com" in (os.getenv("RPC_URL") or ""):
        errors.append("RPC_URL 使用公共节点")
    
    if errors:
        print("\n  [WARN] 配置不完整:")
        for e in errors:
            print(f"    - {e}")
    else:
        print("\n  [OK] 所有凭证配置完整!")
        
        # 尝试初始化 CLOB Client
        try:
            os.environ["PRIVATE_KEY"] = private_key
            os.environ["API_KEY"] = api_key
            os.environ["API_SECRET"] = api_secret
            os.environ["API_PASSPHRASE"] = api_passphrase
            os.environ["RPC_URL"] = rpc_url
            
            # 重新加载配置
            from core.config import SystemConfig
            new_config = SystemConfig()
            
            # 注意: 这里不实际连接, 仅验证配置可被加载
            print(f"\n  配置摘要:")
            print(f"    PRIVATE_KEY:  {private_key[:8]}...{private_key[-6:]}")
            print(f"    API_KEY:      {api_key[:8]}...")
            print(f"    RPC_URL:      {rpc_url[:40]}...")
            print(f"    Chain ID:     137 (Polygon Mainnet)")
            print(f"    CLOB URL:    https://clob.polymarket.com")
            print(f"    WS URL:       wss://ws-subscriptions-clob.polymarket.com")
            
        except Exception as e:
            print(f"\n  [ERROR] 配置验证失败: {e}")


if __name__ == "__main__":
    if "--check" in sys.argv:
        print_header()
        config = check_env()
        if config:
            print("  当前 .env 配置状态:\n")
            required = {
                "PRIVATE_KEY": "L1 钱包私钥",
                "API_KEY": "Polymarket API Key",
                "API_SECRET": "Polymarket API Secret",
                "API_PASSPHRASE": "Polymarket API Passphrase",
                "RPC_URL": "Polygon RPC 节点",
            }
            all_ok = True
            for key, desc in required.items():
                val = config.get(key, "")
                if val:
                    masked = val[:8] + "..." + val[-4:] if len(val) > 12 else "***"
                    print(f"    [OK] {key:20s} = {masked:30s} ({desc})")
                else:
                    print(f"    [--] {key:20s} = (未配置)                  ({desc})")
                    all_ok = False
            
            if all_ok:
                print("\n  [OK] 全部凭证已配置!")
                print("  运行 python test_phase2_5.py --all 开始验证")
            else:
                print("\n  [WARN] 部分凭证未配置, 运行 python setup_credentials.py")
        else:
            print("  .env 文件不存在, 运行 python setup_credentials.py")
    else:
        main()
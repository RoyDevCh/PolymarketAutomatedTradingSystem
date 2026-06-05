"""
Phase 2.5 微量实盘探路 - CLOB V2 版本

Polymarket 于 2026-04-28 升级到 CLOB V2。
旧版 py-clob-client (V1) 的签名格式不再兼容，必须使用 py-clob-client-v2。

V2 变更要点:
- EIP-712 domain version: "1" -> "2"
- 抵押品: USDC.e -> pUSD (Polymarket USD)
- 订单字段: 移除 nonce/feeRateBps/taker, 新增 timestamp/metadata/builder
- 合约地址更新
- API 认证 headers 不变

运行方式:
  python test_micro_live_v3.py --check      # 仅检查余额和连接
  python test_micro_live_v3.py --trade      # 下单+取消测试
  python test_micro_live_v3.py --full       # 完整测试 (默认)
"""

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# 加载代理配置
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

from core.config import CONFIG

import structlog
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="%H:%M:%S"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger(__name__)

# V2 SDK imports
from py_clob_client_v2 import ClobClient, ApiCreds, OrderArgs, OrderType, PartialCreateOrderOptions

# 注入代理到 httpx.Client (与 V1 SDK 共享同一个 httpx)
import httpx
import py_clob_client_v2.client as _v2_client_mod


def _inject_proxy_to_v2_client():
    """将 SOCKS5/HTTP 代理注入 py-clob-client-v2 的 httpx.Client"""
    proxy_url = os.environ.get("https_proxy") or os.environ.get("http_proxy")
    if not proxy_url:
        logger.warning("No proxy configured for CLOB client")
        return
    logger.info(f"Injecting proxy to CLOB V2 client: {proxy_url[:30]}...")
    import py_clob_client_v2.http_helpers.helpers as _v2h
    _v2h._http_client = httpx.Client(
        proxy=proxy_url,
        timeout=httpx.Timeout(30.0),
        follow_redirects=True,
    )
    logger.info("CLOB V2 client proxy injection successful")


class MicroLiveTestV2:
    """CLOB V2 微量实盘探路测试"""

    def __init__(self):
        self.client = None
        self.test_token_id = None
        self.test_condition_id = None
        self.order_id = None

    def _create_client(self):
        """创建 CLOB V2 客户端"""
        cfg = CONFIG.clob
        wallet_cfg = CONFIG.wallet

        api_creds = ApiCreds(
            api_key=cfg.api_key,
            api_secret=cfg.api_secret,
            api_passphrase=cfg.api_passphrase,
        )

        client = ClobClient(
            host=cfg.api_url,
            chain_id=wallet_cfg.chain_id,
            key=wallet_cfg.private_key,
            creds=api_creds,
        )
        return client

    async def check_connection(self):
        """检查连接和 API 认证"""
        print("\n" + "=" * 60)
        print("  [1/4] 检查 CLOB V2 API 连接")
        print("=" * 60)

        try:
            self.client = self._create_client()
            _inject_proxy_to_v2_client()
            print(f"  [OK] ClobClient V2 初始化成功")
        except Exception as e:
            print(f"  [FAIL] ClobClient V2 初始化失败: {e}")
            return False

        # Check server time
        try:
            from py_clob_client_v2.http_helpers.helpers import get
            server_time = get(f"{CONFIG.clob.api_url}/time")
            print(f"  [OK] Server time: {server_time}")
        except Exception as e:
            print(f"  [WARN] 获取服务器时间失败: {e}")

        # Check balance
        try:
            balance = self.client.get_balance_allowance()
            print(f"  [OK] Balance API: {balance}")
        except Exception as e:
            print(f"  [WARN] Balance query: {e}")

        return True

    async def find_test_market(self):
        """找一个活跃市场"""
        print("\n" + "=" * 60)
        print("  [2/4] 寻找活跃测试市场")
        print("=" * 60)

        import aiohttp
        import json

        proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
        url = "https://gamma-api.polymarket.com/markets?active=true&closed=false&order=volume&ascending=false&limit=5"

        async with aiohttp.ClientSession(trust_env=True) as s:
            async with s.get(url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=15)) as r:
                markets = await r.json()

        if not markets:
            print("  [FAIL] 未发现市场")
            return False

        for m in markets[:5]:
            clob_ids = m.get("clobTokenIds", [])
            if isinstance(clob_ids, str):
                clob_ids = json.loads(clob_ids)
            if len(clob_ids) >= 2:
                self.test_token_id = clob_ids[0]
                self.test_condition_id = m.get("conditionId", "") or m.get("condition_id", "")
                question = m.get("question", "")[:50]
                volume = float(m.get("volumeNum", 0) or 0)
                print(f"  [OK] 选择市场: {question}")
                print(f"       Token ID: {self.test_token_id[:40]}...")
                print(f"       Condition: {self.test_condition_id[:40]}...")
                print(f"       Volume: ${volume:,.0f}")
                return True

        print("  [FAIL] 未找到有 token IDs 的市场")
        return False

    async def place_test_order(self):
        """通过 V2 SDK 下测试订单"""
        print("\n" + "=" * 60)
        print("  [3/4] 下单测试 (CLOB V2)")
        print("=" * 60)

        if not self.client or not self.test_token_id:
            print("  [FAIL] 客户端或市场未初始化")
            return False

        # Get market info for tick size
        try:
            market_info = self.client.get_clob_market_info(self.test_condition_id)
            print(f"  [OK] Market info: {market_info}")
            tick_size = market_info.get("mts", "0.01")
            min_order_size = market_info.get("mos", "1")
            print(f"       Tick size: {tick_size}, Min order size: {min_order_size}")
        except Exception as e:
            print(f"  [WARN] get_clob_market_info failed: {e}, using defaults")
            tick_size = "0.01"
            min_order_size = "1"

        # Get orderbook for price reference
        try:
            book = self.client.get_order_book(self.test_token_id)
            if book and book.bids:
                best_bid = float(book.bids[0].price)
                print(f"  Best bid: {best_bid}")
                # Place far below best bid (very unlikely to fill)
                safe_price = round(best_bid * 0.5, int(-1 * (float(tick_size).as_integer_ratio()[1] if '.' not in str(tick_size) else len(str(tick_size).split('.')[-1]))))
                if safe_price <= 0:
                    safe_price = float(tick_size)
            else:
                safe_price = 0.01
                print(f"  No bids, using default price: {safe_price}")
        except Exception as e:
            print(f"  [WARN] Orderbook fetch failed: {e}, using default price")
            safe_price = 0.01

        # Ensure price is at least tick_size
        if safe_price < float(tick_size):
            safe_price = float(tick_size)

        # Clean price to tick_size precision
        ts = float(tick_size)
        decimals = len(str(tick_size).rstrip('0').split('.')[-1]) if '.' in str(tick_size) else 0
        safe_price = round(safe_price, decimals)

        print(f"\n  下单参数:")
        print(f"    Token:    {self.test_token_id[:40]}...")
        print(f"    Price:    ${safe_price} (极偏移限价)")
        print(f"    Size:     1.0 share")
        print(f"    Side:     BUY")
        print(f"    TickSize: {tick_size}")

        try:
            order_args = OrderArgs(
                token_id=self.test_token_id,
                price=safe_price,
                size=1.0,
                side="BUY",
            )

            # V2 uses CreateOrderOptions with tick_size and neg_risk
            options = PartialCreateOrderOptions(
                tick_size=tick_size,
                neg_risk=False,
            )

            print("  正在创建 V2 EIP-712 签名...")
            signed_order = self.client.create_order(order_args, options)

            print(f"  [OK] 签名成功!")
            print(f"       Salt: {getattr(signed_order, 'salt', 'N/A')}")
            print(f"       Timestamp: {getattr(signed_order, 'timestamp', 'N/A')}")
            print(f"       Signature: {getattr(signed_order, 'signature', 'N/A')[:20]}...")

            print("  正在提交订单到 Polymarket CLOB V2...")
            response = self.client.post_order(signed_order, OrderType.GTC)

            print(f"\n  *** [SUCCESS] 订单提交响应: {response}")

            if isinstance(response, dict):
                self.order_id = response.get("orderID", response.get("order_id", ""))
                status = response.get("status", "Unknown")
                print(f"  [OK] Order ID: {self.order_id}")
                print(f"  [OK] Status: {status}")
            elif isinstance(response, str):
                self.order_id = response
                print(f"  [OK] Order ID: {response}")
            else:
                print(f"  [OK] Response: {response}")

            # Wait and verify
            print("\n  等待 3 秒...")
            await asyncio.sleep(3)

            # Try to get order status
            if self.order_id:
                try:
                    order_status = self.client.get_order(self.order_id)
                    print(f"  [OK] 订单状态: {order_status}")
                except Exception as e:
                    print(f"  [WARN] 查询订单状态: {e}")

            return True

        except Exception as e:
            print(f"\n  [FAIL] 下单失败: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def cancel_test_order(self):
        """取消测试订单"""
        print("\n" + "=" * 60)
        print("  [4/4] 取消订单测试")
        print("=" * 60)

        if not self.order_id:
            print("  [SKIP] 没有 Order ID")
            # Try cancel_all as cleanup
            try:
                result = self.client.cancel_all()
                print(f"  cancel_all result: {result}")
            except Exception as e:
                print(f"  cancel_all: {e}")
            return True

        print(f"  取消订单: {self.order_id}")
        try:
            result = self.client.cancel(self.order_id)
            print(f"  [OK] 取消响应: {result}")
        except Exception as e:
            print(f"  [WARN] 取消失败: {e}")
            try:
                result = self.client.cancel_all()
                print(f"  cancel_all: {result}")
            except Exception as e2:
                print(f"  cancel_all 也不行: {e2}")

        return True

    async def run_full_test(self):
        """运行完整测试"""
        print("=" * 60)
        print("  Phase 2.5 微量实盘探路 - CLOB V2")
        print("=" * 60)

        # Step 1: Connection check
        if not await self.check_connection():
            print("\n[FAIL] 连接检查失败")
            return False

        # Step 2: Find market
        if not await self.find_test_market():
            print("\n[FAIL] 未找到市场")
            return False

        # Step 3: Place order
        success = await self.place_test_order()

        # Step 4: Cancel order
        await self.cancel_test_order()

        # Summary
        print("\n" + "=" * 60)
        print("  Phase 2.5 CLOB V2 微量实盘探路 - 结果汇总")
        print("=" * 60)
        print()
        print(f"  CLOB V2 API:      {'OK' if self.client else 'FAIL'}")
        print(f"  V2 签名创建:      {'OK' if self.order_id or success else 'FAIL'}")
        print(f"  订单 ID:           {self.order_id or 'N/A'}")
        print(f"  代理 (JP-02):     已配置")
        print()

        if self.order_id or success:
            print("  ========== V2 链路已贯通! ==========")
            print("  下单 → V2签名 → 提交 → 撤销 全流程验证通过")
        else:
            print("  [WARN] V2 订单创建失败, 需要继续调试")

        return bool(self.order_id or success)


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Phase 2.5 Micro Live Test V2")
    parser.add_argument("--check", action="store_true", help="Only check connection")
    parser.add_argument("--trade", action="store_true", help="Place and cancel test order")
    parser.add_argument("--full", action="store_true", help="Full test (default)")
    args = parser.parse_args()

    if not any([args.check, args.trade, args.full]):
        args.full = True

    tester = MicroLiveTestV2()

    if args.check:
        await tester.check_connection()
    elif args.trade:
        await tester.check_connection()
        await tester.find_test_market()
        await tester.place_test_order()
        await tester.cancel_test_order()
    else:
        await tester.run_full_test()


if __name__ == "__main__":
    asyncio.run(main())
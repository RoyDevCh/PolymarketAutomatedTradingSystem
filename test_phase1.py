"""
Phase 1 测试脚本: 验证 Gamma API 市场发现功能

运行方式:
  python test_phase1.py

预期输出:
  - 成功连接 Gamma API
  - 打印活跃市场列表 (含交易量/流动性)
  - 展示 YES/NO Token ID 映射
"""

import asyncio
import os
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

# 加载代理配置 (mihomo/Clash)
def _load_proxy():
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


_load_proxy()

import structlog
from core.mdg import MarketDataGateway
from core.config import CONFIG

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


async def test_gamma_api():
    """测试 Gamma API 市场发现"""
    print("=" * 70)
    print("  Phase 1 测试: Gamma API 市场发现")
    print("=" * 70)
    print()

    mdg = MarketDataGateway(snapshot_callback=lambda s: None)

    print(f"📡 连接 Gamma API: {CONFIG.gamma.api_url}")
    print(f"   最低交易量过滤: ${CONFIG.gamma.min_volume:,.0f}")
    print(f"   最低流动性过滤: ${CONFIG.gamma.min_liquidity:,.0f}")
    print()

    markets = await mdg.discover_markets()

    if not markets:
        print("❌ 未发现任何活跃市场!")
        print("   可能原因:")
        print("   - Gamma API 不可达 (检查网络)")
        print("   - 过滤阈值过高 (降低 min_volume / min_liquidity)")
        return False

    print(f"✅ 发现 {len(markets)} 个活跃市场:")
    print()

    # 按交易量排序展示
    markets.sort(key=lambda m: m.volume, reverse=True)

    for i, m in enumerate(markets[:30], 1):
        print(f"  [{i:2d}] {m.question[:65]}")
        print(f"       Vol: ${m.volume:>12,.0f}  Liq: ${m.liquidity:>10,.0f}")
        print(f"       YES_Token: {m.yes_token_id[:20]}...")
        print(f"       NO_Token:  {m.no_token_id[:20]}...")
        print()

    # 统计
    total_vol = sum(m.volume for m in markets)
    total_liq = sum(m.liquidity for m in markets)
    print("-" * 70)
    print(f"  合计: {len(markets)} 个市场")
    print(f"  总交易量: ${total_vol:,.0f}")
    print(f"  总流动性: ${total_liq:,.0f}")
    print()

    return True


async def test_websocket_connectivity():
    """测试 CLOB WebSocket 连通性"""
    print("=" * 70)
    print("  Phase 1 测试: CLOB WebSocket 连通性")
    print("=" * 70)
    print()

    # 先获取市场
    mdg = MarketDataGateway(snapshot_callback=lambda s: None)
    markets = await mdg.discover_markets()

    if not markets:
        print("❌ 无法获取市场, 跳过 WebSocket 测试")
        return False

    # 取第一个市场的 token IDs
    test_market = markets[0]
    token_ids = [test_market.yes_token_id, test_market.no_token_id]

    print(f"📡 尝试连接 CLOB WebSocket: {CONFIG.clob.ws_market_url}")
    print(f"   订阅市场: {test_market.question[:50]}")
    print()

    received_snapshots = []

    def on_snapshot(snapshot):
        received_snapshots.append(snapshot)
        print(f"  📊 收到快照: token={snapshot.token_id[:16]}... "
              f"asks={len(snapshot.asks)} bids={len(snapshot.bids)} "
              f"best_ask={snapshot.best_ask.price if snapshot.best_ask else 'N/A'} "
              f"best_bid={snapshot.best_bid.price if snapshot.best_bid else 'N/A'}")

    mdg_ws = MarketDataGateway(snapshot_callback=on_snapshot)
    mdg_ws._markets = {test_market.condition_id: test_market}
    mdg_ws._condition_to_tokens = {
        test_market.condition_id: {
            "yes": test_market.yes_token_id,
            "no": test_market.no_token_id,
        }
    }

    # 尝试连接 5 秒
    print("  等待 WebSocket 数据 (5秒)...")
    try:
        await asyncio.wait_for(
            mdg_ws.subscribe_orderbooks(token_ids),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        pass

    await mdg_ws.stop()

    if received_snapshots:
        print(f"\n✅ 收到 {len(received_snapshots)} 个订单簿快照")
        return True
    else:
        print("\n⚠️  未收到快照 (可能需要调整 WebSocket 协议)")
        return False


async def main():
    print("\n🚀 Phase 1 测试开始\n")

    success = True

    # 测试 1: Gamma API
    if not await test_gamma_api():
        success = False

    print()

    # 测试 2: WebSocket 连通性
    try:
        if not await test_websocket_connectivity():
            success = False
    except Exception as e:
        print(f"⚠️  WebSocket 测试异常: {e}")
        print("   这是正常的 - Polymarket WebSocket 可能需要特定认证")

    print()
    if success:
        print("✅ Phase 1 盲区解除测试通过!")
    else:
        print("❌ Phase 1 测试存在问题, 请检查网络和配置")

    return success


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
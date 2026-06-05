"""
Polymarket Phase 4 - 关联市场发现与统计套利引擎 (Correlation Discovery Engine)

职责:
1. 从 Gamma API 发现同一事件的不同子市场 (condition_id 相关性)
2. 构建条件概率树: P(A) → P(B|A), P(B|¬A)
3. 计算对冲比率: 持有 YES(A) 时需要多少 NO(A∩B) 来对冲
4. 输出 HedgeSignal 给 OEG 执行对冲操作

关联发现逻辑:
  "特朗普赢得大选" ↔ "特朗普赢得宾州" ↔ "特朗普赢得密歇根州"
  P(赢得大选) ≈ P(赢得宾州) × P(宾州|大选) + P(赢得非宾州) × P(非宾州|大选)

  如果我们在大选市场持有多头 (YES 被吃), 
  应该在宾州市场买入 NO(特朗普输宾州) 来对冲,
  而不是傻等大选市场的 NO 限价单被吃。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class CorrelatedMarket:
    """关联市场"""
    condition_id: str
    question: str
    yes_token_id: str
    no_token_id: str
    correlation: float       # 与主市场的相关性 (-1 到 1)
    conditional_prob: float   # P(此市场YES | 主市场YES)
    volume_24h: float
    liquidity: float


@dataclass
class HedgeSignal:
    """对冲信号 — 当持仓超过阈值时触发"""
    signal_id: str
    primary_condition_id: str       # 主市场
    primary_side: str               # 主市场持仓方向 ("YES" or "NO")
    primary_inventory_usd: float    # 主市场持仓金额
    hedge_condition_id: str         # 对冲市场
    hedge_side: str                 # 对冲方向 (与主市场持仓相反的关联方向)
    hedge_size_usd: float           # 对冲金额
    hedge_ratio: float             # 对冲比率 (持有$1主市场 → 对冲$hedge_ratio)
    correlation: float             # 关联系数
    expected_cost_savings: float    # 预期成本节省 (vs 等待原市场成交)
    timestamp: float = field(default_factory=time.time)


class CorrelationEngine:
    """
    关联市场发现与统计套利引擎
    
    从 Gamma API 批量获取市场数据, 按事件分组发现关联市场,
    计算条件概率和对冲比率。
    """

    def __init__(self, gamma_url: str = "https://gamma-api.polymarket.com"):
        self.gamma_url = gamma_url
        self._markets: dict[str, dict] = {}  # condition_id → market data
        self._event_groups: dict[str, list[str]] = {}  # event_slug → [condition_ids]
        self._correlations: dict[tuple[str, str], float] = {}  # (cid1, cid2) → correlation
        self._last_fetch: float = 0
        self._fetch_interval: float = 300  # 5分钟更新一次

    async def fetch_markets(self) -> dict[str, list[CorrelatedMarket]]:
        """
        从 Gamma API 获取所有活跃市场, 按事件分组
        
        Returns:
            event_slug → list of CorrelatedMarket
        """
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30.0) as client:
                markets = []
                offset = 0
                limit = 100
                
                while True:
                    resp = await client.get(
                        f"{self.gamma_url}/markets",
                        params={
                            "active": "true",
                            "closed": "false",
                            "limit": limit,
                            "offset": offset,
                        }
                    )
                    if resp.status_code != 200:
                        logger.error("gamma_fetch_error", status=resp.status_code)
                        break
                    
                    data = resp.json()
                    if not data:
                        break
                    
                    for m in data:
                        condition_id = m.get("conditionId", "")
                        if not condition_id:
                            continue
                            
                        self._markets[condition_id] = m
                        event_slug = m.get("slug", m.get("groupItemTitle", ""))
                        
                        if event_slug not in self._event_groups:
                            self._event_groups[event_slug] = []
                        if condition_id not in self._event_groups[event_slug]:
                            self._event_groups[event_slug].append(condition_id)
                    
                    if len(data) < limit:
                        break
                    offset += limit
                
                self._last_fetch = time.time()
                logger.info("gamma_markets_fetched", total=len(self._markets), events=len(self._event_groups))
                
        except Exception as e:
            logger.error("gamma_fetch_exception", error=str(e))

        return self._build_correlation_map()

    def _build_correlation_map(self) -> dict[str, list[CorrelatedMarket]]:
        """
        构建关联市场映射
        
        规则:
        1. 同一事件 (event_slug 相同) → 相关性 = 1.0
        2. 同一类事件 (如不同州的选举) → 相关性 = 0.7-0.9
        3. 互斥事件 (同一事件的不同结果) → 相关性 = -1.0
        """
        result: dict[str, list[CorrelatedMarket]] = {}
        
        for event_slug, condition_ids in self._event_groups.items():
            if len(condition_ids) < 2:
                continue  # 单一市场没有关联

            for cid in condition_ids:
                market = self._markets.get(cid, {})
                correlated = []
                
                for other_cid in condition_ids:
                    if other_cid == cid:
                        continue
                    
                    other_market = self._markets.get(other_cid, {})
                    other_question = other_market.get("question", "")
                    
                    # 同一事件 = 高度相关
                    # 互斥结果 → correlation = -1.0
                    # 补充结果 → correlation = 正值
                    
                    # 简化相关度计算: 同一事件内, 假设相关性 = 0.8
                    # 实际应从历史价格数据计算
                    correlation = 0.8  # placeholder
                    
                    # 条件概率: P(other=YES | this=YES)
                    # 同一事件内, 如果是互斥结果, P = 0
                    # 否则 P ≈ correlation
                    conditional_prob = correlation
                    
                    correlated.append(CorrelatedMarket(
                        condition_id=other_cid,
                        question=other_question,
                        yes_token_id=other_market.get("clobTokenIds", ["", ""])[0] if isinstance(other_market.get("clobTokenIds"), list) else "",
                        no_token_id=other_market.get("clobTokenIds", ["", ""])[1] if isinstance(other_market.get("clobTokenIds"), list) else "",
                        correlation=correlation,
                        conditional_prob=conditional_prob,
                        volume_24h=float(other_market.get("volume", 0)),
                        liquidity=float(other_market.get("liquidity_num", 0)),
                    ))
                
                result[cid] = correlated
                
                # 存储相关系数
                for cm in correlated:
                    key = (cid, cm.condition_id)
                    self._correlations[key] = cm.correlation

        return result

    def calculate_hedge_ratio(
        self,
        primary_condition_id: str,
        primary_side: str,
        hedge_condition_id: str,
    ) -> float:
        """
        计算对冲比率
        
        最优对冲比率 = correlation * (volatility_primary / volatility_hedge)
        
        简化版: hedge_ratio = |correlation|
        """
        key = (primary_condition_id, hedge_condition_id)
        return abs(self._correlations.get(key, 0.5))

    def get_event_group(self, condition_id: str) -> list[str]:
        """获取同一事件的所有市场"""
        for slug, cids in self._event_groups.items():
            if condition_id in cids:
                return cids
        return []

    def get_stats(self) -> dict:
        """返回引擎统计信息"""
        return {
            "markets_loaded": len(self._markets),
            "event_groups": len(self._event_groups),
            "correlations_computed": len(self._correlations),
            "last_fetch": self._last_fetch,
        }
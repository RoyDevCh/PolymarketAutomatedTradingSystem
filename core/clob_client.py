"""
Polymarket 自动套利系统 - CLOB Client 单例封装
遵循隔离原则: py-clob-client 实例化集中在此模块
所有执行逻辑通过调用该单例完成
"""

from __future__ import annotations

import logging
from typing import Optional

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds

from core.config import CONFIG

logger = logging.getLogger(__name__)


class ClobClientManager:
    """
    py-clob-client 的单例管理器
    
    设计原则:
    1. 全局只创建一个 ClobClient 实例
    2. 密钥从 .env 加载, 代码中无硬编码
    3. 提供 create() / get() 双入口, 惰性初始化
    """

    _instance: Optional[ClobClient] = None
    _initialized: bool = False

    @classmethod
    def create(cls) -> ClobClient:
        """
        创建并初始化 CLOB Client 单例
        
        流程:
        1. 使用 L1 私钥 + L2 凭证构建 ApiCreds
        2. 指定 Polygon Mainnet (chain_id=137)
        3. 调用 derive_api_key 完成链上注册 (仅需一次)
        """
        if cls._instance is not None:
            logger.debug("ClobClient 单例已存在, 跳过重复创建")
            return cls._instance

        logger.info("正在初始化 CLOB Client...")

        # 校验必要凭证
        cfg = CONFIG.clob
        wallet_cfg = CONFIG.wallet

        if not wallet_cfg.private_key:
            raise RuntimeError("PRIVATE_KEY 未配置, 无法初始化 CLOB Client")
        if not all([cfg.api_key, cfg.api_secret, cfg.api_passphrase]):
            raise RuntimeError("L2 API 凭证不完整, 无法初始化 CLOB Client")

        # 构造 API 凭证
        api_creds = ApiCreds(
            api_key=cfg.api_key,
            api_secret=cfg.api_secret,
            api_passphrase=cfg.api_passphrase,
        )

        # 实例化 ClobClient (链ID=137 → Polygon Mainnet)
        client = ClobClient(
            host=cfg.api_url,
            key=wallet_cfg.private_key,
            chain_id=wallet_cfg.chain_id,
            creds=api_creds,
        )

        cls._instance = client
        cls._initialized = True
        logger.info("CLOB Client 初始化完成 ✓")
        return cls._instance

    @classmethod
    def get(cls) -> ClobClient:
        """获取已初始化的 CLOB Client 单例, 若未初始化则自动创建"""
        if cls._instance is None:
            return cls.create()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """重置单例 (仅用于测试)"""
        cls._instance = None
        cls._initialized = False
        logger.warning("CLOB Client 单例已重置")


# 便捷访问
def get_clob_client() -> ClobClient:
    """全局入口: 获取 CLOB Client 单例"""
    return ClobClientManager.get()
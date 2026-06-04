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
    4. 支持三阶段初始化:
       - Level 1: 仅 PRIVATE_KEY → 可调用 create_api_key / derive_api_key
       - Level 2: PRIVATE_KEY + API_KEY/SECRET/PASSPHRASE → 完整交易能力
    """

    _instance: Optional[ClobClient] = None
    _initialized: bool = False

    @classmethod
    def create(cls) -> ClobClient:
        """
        创建并初始化 CLOB Client 单例
        
        支持两种模式:
        1. Level 1 (仅私钥): 用途是 create_api_key
        2. Level 2 (私钥 + API 凭证): 完整交易能力
        """
        if cls._instance is not None:
            logger.debug("ClobClient 单例已存在, 跳过重复创建")
            return cls._instance

        logger.info("正在初始化 CLOB Client...")

        cfg = CONFIG.clob
        wallet_cfg = CONFIG.wallet

        if not wallet_cfg.private_key:
            raise RuntimeError(
                "PRIVATE_KEY 未配置!\n"
                "请按照以下步骤获取:\n"
                "1. 创建新的 MetaMask 钱包 (切勿使用已有主钱包)\n"
                "2. 导出私钥 (MetaMask → 账户详情 → 导出私钥)\n"
                "3. 将私钥填入 .env 文件的 PRIVATE_KEY 字段"
            )

        # 检查是否有 L2 凭证
        has_l2_creds = all([cfg.api_key, cfg.api_secret, cfg.api_passphrase])

        if has_l2_creds:
            # Level 2: 完整交易能力
            api_creds = ApiCreds(
                api_key=cfg.api_key,
                api_secret=cfg.api_secret,
                api_passphrase=cfg.api_passphrase,
            )
            client = ClobClient(
                host=cfg.api_url,
                key=wallet_cfg.private_key,
                chain_id=wallet_cfg.chain_id,
                creds=api_creds,
            )
            logger.info("CLOB Client 初始化完成 (Level 2 - 完整交易能力)")
        else:
            # Level 1: 仅认证, 可用于 create_api_key
            client = ClobClient(
                host=cfg.api_url,
                key=wallet_cfg.private_key,
                chain_id=wallet_cfg.chain_id,
            )
            logger.warning(
                "CLOB Client 初始化完成 (Level 1 - 仅认证模式)\n"
                "L2 API 凭证未配置, 无法执行交易。\n"
                "请运行 python setup_credentials.py 获取 API 凭证\n"
                "或手动在 .env 中填入 API_KEY, API_SECRET, API_PASSPHRASE"
            )

        cls._instance = client
        cls._initialized = True
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
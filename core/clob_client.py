"""
Polymarket 自动套利系统 - CLOB Client 单例封装
遵循隔离原则: py-clob-client-v2 实例化集中在此模块

v1.3: 迁移至 py-clob-client-v2, 支持 Deposit Wallet (POLY_1271)
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import ApiCreds, AssetType, BalanceAllowanceParams

from core.config import CONFIG

logger = logging.getLogger(__name__)


def _inject_proxy_to_clob_client() -> None:
    """将 HTTP/SOCKS 代理注入 py-clob-client-v2 的 httpx.Client"""
    import httpx
    import py_clob_client_v2.http_helpers.helpers as h

    proxy_url = os.environ.get("https_proxy") or os.environ.get("http_proxy")
    if not proxy_url:
        logger.warning("No proxy configured for CLOB client.")
        return

    logger.info("Injecting proxy to CLOB client: %s...", proxy_url[:30])
    try:
        h._http_client = httpx.Client(
            proxy=proxy_url,
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
        )
        logger.info("CLOB client proxy injection successful")
    except Exception as e:
        logger.error("Failed to inject proxy: %s", e)


class ClobClientManager:
    """py-clob-client-v2 单例管理器"""

    _instance: Optional[ClobClient] = None
    _initialized: bool = False

    @classmethod
    def create(cls) -> ClobClient:
        if cls._instance is not None:
            return cls._instance

        logger.info("Initializing CLOB Client v2...")

        cfg = CONFIG.clob
        wallet_cfg = CONFIG.wallet

        if not wallet_cfg.private_key:
            raise RuntimeError("PRIVATE_KEY not configured in .env")

        if not wallet_cfg.deposit_wallet:
            raise RuntimeError("DEPOSIT_WALLET not configured in .env")

        has_l2 = all([cfg.api_key, cfg.api_secret, cfg.api_passphrase])

        kwargs = dict(
            host=cfg.api_url,
            key=wallet_cfg.private_key,
            chain_id=wallet_cfg.chain_id,
            signature_type=wallet_cfg.signature_type,
            funder=wallet_cfg.deposit_wallet,
        )

        if has_l2:
            kwargs["creds"] = ApiCreds(
                api_key=cfg.api_key,
                api_secret=cfg.api_secret,
                api_passphrase=cfg.api_passphrase,
            )
            client = ClobClient(**kwargs)
            logger.info(
                "CLOB Client v2 ready (sig_type=%s, funder=%s...%s)",
                wallet_cfg.signature_type,
                wallet_cfg.deposit_wallet[:10],
                wallet_cfg.deposit_wallet[-6:],
            )
        else:
            client = ClobClient(**kwargs)
            logger.warning("CLOB Client v2 Level 1 only - missing L2 API creds")

        cls._instance = client
        cls._initialized = True
        _inject_proxy_to_clob_client()
        return cls._instance

    @classmethod
    def get(cls) -> ClobClient:
        if cls._instance is None:
            return cls.create()
        _inject_proxy_to_clob_client()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None
        cls._initialized = False


def get_clob_client() -> ClobClient:
    return ClobClientManager.get()


def get_collateral_balance_usd(client: ClobClient | None = None) -> float | None:
    """Return CLOB collateral (USDC) balance in dollars, or None on failure."""
    try:
        clob = client or get_clob_client()
        wallet_cfg = CONFIG.wallet
        params = BalanceAllowanceParams(
            asset_type=AssetType.COLLATERAL,
            signature_type=wallet_cfg.signature_type,
        )
        try:
            clob.update_balance_allowance(params)
        except Exception:
            logger.debug("update_balance_allowance skipped", exc_info=True)
        bal = clob.get_balance_allowance(params)
        if isinstance(bal, dict):
            raw = bal.get("balance", "0")
        else:
            raw = getattr(bal, "balance", "0")
        return int(str(raw)) / 1e6
    except Exception as exc:
        logger.warning("Failed to fetch CLOB collateral balance: %s", exc)
        return None

"""
Polymarket 微服务总线 - 进程间通信层

替代 asyncio.Queue，使用 SQLite 作为消息总线实现进程间解耦。
每个微服务独立运行，通过 DB 轮询实现数据流转。

架构:
┌─────────┐  snapshot_queue  ┌─────────┐  signal_queue  ┌─────────┐
│   MDG   │ ──────────────→ │   SPE   │ ─────────────→ │   OEG   │
│ (市场数据)│   (SQLite)      │ (策略引擎)│   (SQLite)     │ (订单执行)│
└─────────┘                  └─────────┘                 └─────────┘
                                                                │
                                    result_queue                │
                                        (SQLite)                 ▼
                                                           ┌─────────┐
                                                           │   RMC   │
                                                           │ (风控中心)│
                                                           └─────────┘
"""

from __future__ import annotations

import json
import sqlite3
import time
import asyncio
import structlog
from pathlib import Path
from typing import Optional

logger = structlog.get_logger(__name__)

DB_PATH = str(Path(__file__).resolve().parent.parent / "db" / "arbitrage.db")


class MessageBus:
    """
    基于 SQLite 的微服务消息总线。
    
    三条队列:
    - snapshot_queue: MDG → SPE (订单簿快照)
    - signal_queue:  SPE → OEG (交易信号)  
    - result_queue:  OEG → RMC (执行结果)
    
    设计原则:
    - 写入端: INSERT + COMMIT (快速)
    - 读取端: SELECT pending → UPDATE processed (轮询)
    - 清理: 定期 DELETE 已处理超时记录 (维护线程)
    - 幂等: signal_id UNIQUE 约束防止重复
    """
    
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._ensure_tables()
    
    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn
    
    def _ensure_tables(self) -> None:
        """确保消息队列表存在"""
        schema_path = Path(__file__).resolve().parent.parent / "db" / "queue_schema.sql"
        if schema_path.exists():
            conn = self._get_conn()
            try:
                conn.executescript(schema_path.read_text())
                conn.commit()
            finally:
                conn.close()
    
    # ── Snapshot Queue (MDG → SPE) ──
    
    def push_snapshot(self, token_id: str, condition_id: str,
                      asks_json: str, bids_json: str) -> int:
        """MDG 推送订单簿快照"""
        conn = self._get_conn()
        try:
            cur = conn.execute(
                """INSERT INTO snapshot_queue 
                   (timestamp, token_id, condition_id, asks_json, bids_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (time.time(), token_id, condition_id, asks_json, bids_json, time.time())
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()
    
    def poll_snapshots(self, limit: int = 100, max_age: float = 30.0) -> list[dict]:
        """SPE 拉取未处理的快照"""
        conn = self._get_conn()
        try:
            cutoff = time.time() - max_age
            rows = conn.execute(
                """SELECT id, timestamp, token_id, condition_id, asks_json, bids_json
                   FROM snapshot_queue
                   WHERE processed = 0 AND created_at > ?
                   ORDER BY created_at ASC LIMIT ?""",
                (cutoff, limit)
            ).fetchall()
            
            # 标记为已处理
            if rows:
                ids = ",".join(str(r[0]) for r in rows)
                conn.execute(f"UPDATE snapshot_queue SET processed = 1 WHERE id IN ({ids})")
                conn.commit()
            
            return [
                {
                    "id": r[0], "timestamp": r[1], "token_id": r[2],
                    "condition_id": r[3], "asks": json.loads(r[4]), "bids": json.loads(r[5]),
                }
                for r in rows
            ]
        finally:
            conn.close()
    
    # ── Signal Queue (SPE → OEG) ──
    
    def push_signal(self, signal_id: str, condition_id: str,
                    market_question: str = "", strategy: str = "maker",
                    yes_token_id: str = "", no_token_id: str = "",
                    yes_price: float = 0, no_price: float = 0,
                    yes_size: float = 0, no_size: float = 0,
                    expected_profit: float = 0, slippage_estimate: float = 0,
                    total_cost: float = 0) -> int:
        """SPE 推送交易信号"""
        conn = self._get_conn()
        try:
            cur = conn.execute(
                """INSERT OR IGNORE INTO signal_queue
                   (timestamp, signal_id, condition_id, market_question, strategy,
                    yes_token_id, no_token_id, yes_price, no_price,
                    yes_size, no_size, expected_profit, slippage_estimate,
                    total_cost, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (time.time(), signal_id, condition_id, market_question, strategy,
                 yes_token_id, no_token_id, yes_price, no_price,
                 yes_size, no_size, expected_profit, slippage_estimate,
                 total_cost, time.time())
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()
    
    def poll_signals(self, limit: int = 10, max_age: float = 300.0) -> list[dict]:
        """OEG 拉取未处理的交易信号"""
        conn = self._get_conn()
        try:
            cutoff = time.time() - max_age
            rows = conn.execute(
                """SELECT id, timestamp, signal_id, condition_id, market_question, strategy,
                          yes_token_id, no_token_id, yes_price, no_price,
                          yes_size, no_size, expected_profit, slippage_estimate, total_cost
                   FROM signal_queue
                   WHERE processed = 0 AND created_at > ?
                   ORDER BY created_at ASC LIMIT ?""",
                (cutoff, limit)
            ).fetchall()
            
            if rows:
                ids = ",".join(str(r[0]) for r in rows)
                conn.execute(f"UPDATE signal_queue SET processed = 1 WHERE id IN ({ids})")
                conn.commit()
            
            return [
                {
                    "id": r[0], "timestamp": r[1], "signal_id": r[2],
                    "condition_id": r[3], "market_question": r[4], "strategy": r[5],
                    "yes_token_id": r[6], "no_token_id": r[7],
                    "yes_price": r[8], "no_price": r[9],
                    "yes_size": r[10], "no_size": r[11],
                    "expected_profit": r[12], "slippage_estimate": r[13],
                    "total_cost": r[14],
                }
                for r in rows
            ]
        finally:
            conn.close()
    
    # ── Result Queue (OEG → RMC) ──
    
    def push_result(self, signal_id: str, condition_id: str,
                    yes_order_id: str = "", no_order_id: str = "",
                    yes_status: str = "PENDING", no_status: str = "PENDING",
                    yes_fill_price: float = 0, no_fill_price: float = 0,
                    yes_filled_size: float = 0, no_filled_size: float = 0,
                    realized_profit: float = 0, has_leg_risk: bool = False) -> int:
        """OEG 推送执行结果"""
        conn = self._get_conn()
        try:
            cur = conn.execute(
                """INSERT INTO result_queue
                   (timestamp, signal_id, condition_id, yes_order_id, no_order_id,
                    yes_status, no_status, yes_fill_price, no_fill_price,
                    yes_filled_size, no_filled_size, realized_profit,
                    has_leg_risk, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (time.time(), signal_id, condition_id, yes_order_id, no_order_id,
                 yes_status, no_status, yes_fill_price, no_fill_price,
                 yes_filled_size, no_filled_size, realized_profit,
                 1 if has_leg_risk else 0, time.time())
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()
    
    def poll_results(self, limit: int = 50, max_age: float = 3600.0) -> list[dict]:
        """RMC 拉取未处理的执行结果"""
        conn = self._get_conn()
        try:
            cutoff = time.time() - max_age
            rows = conn.execute(
                """SELECT id, timestamp, signal_id, condition_id,
                          yes_order_id, no_order_id, yes_status, no_status,
                          yes_fill_price, no_fill_price, yes_filled_size, no_filled_size,
                          realized_profit, has_leg_risk
                   FROM result_queue
                   WHERE processed = 0 AND created_at > ?
                   ORDER BY created_at ASC LIMIT ?""",
                (cutoff, limit)
            ).fetchall()
            
            if rows:
                ids = ",".join(str(r[0]) for r in rows)
                conn.execute(f"UPDATE result_queue SET processed = 1 WHERE id IN ({ids})")
                conn.commit()
            
            return [
                {
                    "id": r[0], "timestamp": r[1], "signal_id": r[2],
                    "condition_id": r[3], "yes_order_id": r[4], "no_order_id": r[5],
                    "yes_status": r[6], "no_status": r[7],
                    "yes_fill_price": r[8], "no_fill_price": r[9],
                    "yes_filled_size": r[10], "no_filled_size": r[11],
                    "realized_profit": r[12], "has_leg_risk": bool(r[13]),
                }
                for r in rows
            ]
        finally:
            conn.close()
    
    # ── Maintenance ──
    
    def cleanup(self, max_age_hours: float = 24.0) -> dict:
        """清理已处理且超时的消息"""
        conn = self._get_conn()
        try:
            cutoff = time.time() - max_age_hours * 3600
            result = {}
            for table in ["snapshot_queue", "signal_queue", "result_queue"]:
                cur = conn.execute(
                    f"DELETE FROM {table} WHERE processed = 1 AND created_at < ?",
                    (cutoff,)
                )
                result[table] = cur.rowcount
            conn.commit()
            return result
        finally:
            conn.close()
    
    def queue_depth(self) -> dict:
        """查看各队列深度"""
        conn = self._get_conn()
        try:
            result = {}
            for table, name in [
                ("snapshot_queue", "snapshots"),
                ("signal_queue", "signals"),
                ("result_queue", "results"),
            ]:
                pending = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE processed = 0"
                ).fetchone()[0]
                total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                result[name] = {"pending": pending, "total": total}
            return result
        finally:
            conn.close()
    
    # ── Service Lock ──
    
    def acquire_lock(self, service_name: str, pid: int) -> bool:
        """获取服务锁 (防止重复运行)"""
        conn = self._get_conn()
        try:
            # 清理超时锁 (5 分钟无心跳则释放)
            conn.execute(
                "DELETE FROM service_lock WHERE heartbeat_at < ?",
                (time.time() - 300,)
            )
            
            # 尝试获取锁
            existing = conn.execute(
                "SELECT pid FROM service_lock WHERE service_name = ?",
                (service_name,)
            ).fetchone()
            
            if existing and existing[0] != pid:
                return False  # 已被其他进程持有
            
            conn.execute(
                """INSERT OR REPLACE INTO service_lock 
                   (service_name, pid, started_at, heartbeat_at)
                   VALUES (?, ?, ?, ?)""",
                (service_name, pid, time.time(), time.time())
            )
            conn.commit()
            return True
        finally:
            conn.close()
    
    def heartbeat(self, service_name: str, pid: int) -> None:
        """刷新服务心跳"""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE service_lock SET heartbeat_at = ? WHERE service_name = ? AND pid = ?",
                (time.time(), service_name, pid)
            )
            conn.commit()
        finally:
            conn.close()
    
    def release_lock(self, service_name: str, pid: int) -> None:
        """释放服务锁"""
        conn = self._get_conn()
        try:
            conn.execute(
                "DELETE FROM service_lock WHERE service_name = ? AND pid = ?",
                (service_name, pid)
            )
            conn.commit()
        finally:
            conn.close()


# 全局单例
_bus: Optional[MessageBus] = None

def get_bus(db_path: str = DB_PATH) -> MessageBus:
    global _bus
    if _bus is None:
        _bus = MessageBus(db_path)
    return _bus
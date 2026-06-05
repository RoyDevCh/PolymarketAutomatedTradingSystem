-- Polymarket 微服务间通信表
-- 用于替代 asyncio.Queue，实现进程间解耦

-- 订单簿快照队列 (替代 MDG → SPE 的 asyncio.Queue)
CREATE TABLE IF NOT EXISTS snapshot_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    token_id TEXT NOT NULL,
    condition_id TEXT,
    asks_json TEXT NOT NULL,   -- JSON 序列化的 asks
    bids_json TEXT NOT NULL,   -- JSON 序列化的 bids
    processed INTEGER DEFAULT 0,  -- 0=pending, 1=processed by SPE
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshot_pending ON snapshot_queue(processed, created_at);
CREATE INDEX IF NOT EXISTS idx_snapshot_token ON snapshot_queue(token_id);

-- 交易信号队列 (替代 SPE → OEG 的 asyncio.Queue)
CREATE TABLE IF NOT EXISTS signal_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    signal_id TEXT NOT NULL UNIQUE,
    condition_id TEXT NOT NULL,
    market_question TEXT,
    strategy TEXT,            -- 'maker' or 'cross'
    yes_token_id TEXT,
    no_token_id TEXT,
    yes_price REAL,
    no_price REAL,
    yes_size REAL,
    no_size REAL,
    expected_profit REAL,
    slippage_estimate REAL,
    total_cost REAL,
    processed INTEGER DEFAULT 0,  -- 0=pending, 1=processed by OEG
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signal_pending ON signal_queue(processed, created_at);
CREATE INDEX IF NOT EXISTS idx_signal_id ON signal_queue(signal_id);

-- 执行结果队列 (OEG → RMC)
CREATE TABLE IF NOT EXISTS result_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    signal_id TEXT NOT NULL,
    condition_id TEXT NOT NULL,
    yes_order_id TEXT,
    no_order_id TEXT,
    yes_status TEXT,
    no_status TEXT,
    yes_fill_price REAL,
    no_fill_price REAL,
    yes_filled_size REAL,
    no_filled_size REAL,
    realized_profit REAL,
    has_leg_risk INTEGER DEFAULT 0,
    processed INTEGER DEFAULT 0,  -- 0=pending, 1=processed by RMC
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_result_pending ON result_queue(processed, created_at);

-- 架构锁 (防止多个实例同时运行同一服务)
CREATE TABLE IF NOT EXISTS service_lock (
    service_name TEXT PRIMARY KEY,
    pid INTEGER NOT NULL,
    started_at REAL NOT NULL,
    heartbeat_at REAL NOT NULL
);

-- 清理函数: 定期清除已处理且超时的消息
-- (由 RMC maintenance 或独立 cleanup 任务调用)
CREATE VIEW IF NOT EXISTS v_queue_depth AS
SELECT
    'snapshot' as queue_name,
    COUNT(*) as pending,
    (SELECT COUNT(*) FROM snapshot_queue WHERE processed = 1 AND created_at > strftime('%s','now') - 3600) as processed_last_hour
FROM snapshot_queue WHERE processed = 0
UNION ALL
SELECT
    'signal' as queue_name,
    COUNT(*) as pending,
    (SELECT COUNT(*) FROM signal_queue WHERE processed = 1 AND created_at > strftime('%s','now') - 3600) as processed_last_hour
FROM signal_queue WHERE processed = 0
UNION ALL
SELECT
    'result' as queue_name,
    COUNT(*) as pending,
    (SELECT COUNT(*) FROM result_queue WHERE processed = 1 AND created_at > strftime('%s','now') - 3600) as processed_last_hour
FROM result_queue WHERE processed = 0;
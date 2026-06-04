-- Polymarket 自动套利系统 - 数据库 Schema
-- 用于 Phase 2 影子系统和 Phase 3+ 实盘的持久化层
-- 数据库: SQLite (aiosqlite 异步驱动)

-- ============================================================
-- 交易日志表 - 记录每笔套利信号与执行结果
-- ============================================================
CREATE TABLE IF NOT EXISTS trade_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    signal_id TEXT NOT NULL,
    condition_id TEXT NOT NULL,
    market_question TEXT,
    yes_token_id TEXT,
    no_token_id TEXT,
    yes_price REAL,
    no_price REAL,
    yes_size REAL,
    no_size REAL,
    expected_profit REAL,
    realized_profit REAL,
    yes_order_id TEXT,
    no_order_id TEXT,
    yes_status TEXT,      -- MATCHED / FAILED / PENDING / CANCELLED
    no_status TEXT,
    yes_fill_price REAL,
    no_fill_price REAL,
    yes_filled_size REAL,
    no_filled_size REAL,
    slippage_estimate REAL,
    has_leg_risk INTEGER DEFAULT 0,
    gas_cost REAL DEFAULT 0.0,

    -- 索引
    FOREIGN KEY (condition_id) REFERENCES markets(condition_id)
);

CREATE INDEX IF NOT EXISTS idx_trade_log_timestamp ON trade_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_trade_log_condition ON trade_log(condition_id);
CREATE INDEX IF NOT EXISTS idx_trade_log_signal ON trade_log(signal_id);

-- ============================================================
-- 熔断事件日志表
-- ============================================================
CREATE TABLE IF NOT EXISTS circuit_breaker_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    breaker_type TEXT NOT NULL,     -- LEG_RISK / CONSECUTIVE_FAIL / SLIPPAGE_EXCEEDED / NETWORK_TIMEOUT
    condition_id TEXT,
    message TEXT,
    cooldown_until REAL
);

CREATE INDEX IF NOT EXISTS idx_cb_log_timestamp ON circuit_breaker_log(timestamp);

-- ============================================================
-- 信号统计汇总表 (每小时聚合)
-- ============================================================
CREATE TABLE IF NOT EXISTS signal_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    total_signals INTEGER DEFAULT 0,
    total_arbitrages INTEGER DEFAULT 0,
    total_profit REAL DEFAULT 0.0,
    total_leg_risks INTEGER DEFAULT 0,
    avg_slippage REAL DEFAULT 0.0
);

-- ============================================================
-- 市场信息缓存表
-- ============================================================
CREATE TABLE IF NOT EXISTS markets (
    condition_id TEXT PRIMARY KEY,
    question TEXT,
    yes_token_id TEXT,
    no_token_id TEXT,
    active INTEGER DEFAULT 1,
    volume REAL DEFAULT 0.0,
    liquidity REAL DEFAULT 0.0,
    first_seen REAL,
    last_updated REAL
);

-- ============================================================
-- 有用的查询视图
-- ============================================================

-- 最近24小时盈亏概览
CREATE VIEW IF NOT EXISTS v_daily_pnl AS
SELECT
    date(timestamp, 'unixepoch') as trade_date,
    COUNT(*) as total_trades,
    SUM(CASE WHEN realized_profit > 0 THEN 1 ELSE 0 END) as winning_trades,
    SUM(realized_profit) as total_profit,
    AVG(slippage_estimate) as avg_slippage,
    SUM(CASE WHEN has_leg_risk = 1 THEN 1 ELSE 0 END) as leg_risks
FROM trade_log
GROUP BY date(timestamp, 'unixepoch')
ORDER BY trade_date DESC;

-- 被熔断的市场
CREATE VIEW IF NOT EXISTS v_active_breakers AS
SELECT
    breaker_type,
    condition_id,
    message,
    datetime(cooldown_until, 'unixepoch') as cooldown_until_utc
FROM circuit_breaker_log
WHERE cooldown_until > strftime('%s', 'now')
ORDER BY cooldown_until DESC;
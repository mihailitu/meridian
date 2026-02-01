-- Discovery service tables
-- Stores discovered symbols and screener results

-- Discovered symbols table
CREATE TABLE IF NOT EXISTS discovered_symbols (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    source VARCHAR(50) NOT NULL,
    score DOUBLE PRECISION NOT NULL,
    price DOUBLE PRECISION,
    volume BIGINT,
    change_pct DOUBLE PRECISION,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB DEFAULT '{}',
    UNIQUE(symbol, source, discovered_at)
);

-- Index for efficient querying
CREATE INDEX IF NOT EXISTS idx_discovered_symbols_symbol ON discovered_symbols(symbol);
CREATE INDEX IF NOT EXISTS idx_discovered_symbols_source ON discovered_symbols(source);
CREATE INDEX IF NOT EXISTS idx_discovered_symbols_discovered_at ON discovered_symbols(discovered_at DESC);
CREATE INDEX IF NOT EXISTS idx_discovered_symbols_score ON discovered_symbols(score DESC);

-- Screener runs table (tracks when screeners were executed)
CREATE TABLE IF NOT EXISTS screener_runs (
    id SERIAL PRIMARY KEY,
    screener_name VARCHAR(100) NOT NULL,
    screener_type VARCHAR(50) NOT NULL,
    match_count INTEGER NOT NULL DEFAULT 0,
    total_scanned INTEGER NOT NULL DEFAULT 0,
    scan_time_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    run_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_screener_runs_name ON screener_runs(screener_name);
CREATE INDEX IF NOT EXISTS idx_screener_runs_run_at ON screener_runs(run_at DESC);

-- Retention policy: keep discovered symbols for 7 days
-- This can be adjusted based on requirements
-- SELECT add_retention_policy('discovered_symbols', INTERVAL '7 days', if_not_exists => TRUE);

-- Initialize TimescaleDB and create tables

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Bars table (time-series)
CREATE TABLE bars (
    time        TIMESTAMPTZ     NOT NULL,
    symbol      VARCHAR(20)     NOT NULL,
    interval    VARCHAR(10)     NOT NULL,
    open        DECIMAL(18,6)   NOT NULL,
    high        DECIMAL(18,6)   NOT NULL,
    low         DECIMAL(18,6)   NOT NULL,
    close       DECIMAL(18,6)   NOT NULL,
    volume      BIGINT          NOT NULL,
    sma_20      DECIMAL(18,6),
    rsi_14      DECIMAL(8,4),
    created_at  TIMESTAMPTZ     DEFAULT NOW()
);

SELECT create_hypertable('bars', 'time');

CREATE UNIQUE INDEX idx_bars_symbol_interval_time
    ON bars (symbol, interval, time DESC);

-- Positions table
CREATE TABLE positions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id     VARCHAR(50)     NOT NULL,
    symbol          VARCHAR(20)     NOT NULL,
    side            VARCHAR(10)     NOT NULL,
    quantity        DECIMAL(18,8)   NOT NULL,
    avg_entry_price DECIMAL(18,6)   NOT NULL,
    current_price   DECIMAL(18,6),
    unrealized_pnl  DECIMAL(18,2),
    realized_pnl    DECIMAL(18,2)   DEFAULT 0,
    opened_at       TIMESTAMPTZ     DEFAULT NOW(),
    closed_at       TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ     DEFAULT NOW(),
    UNIQUE(strategy_id, symbol)
);

CREATE INDEX idx_positions_strategy ON positions (strategy_id);
CREATE INDEX idx_positions_open ON positions (strategy_id) WHERE closed_at IS NULL;

-- Orders table
CREATE TABLE orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id     VARCHAR(50)     NOT NULL,
    symbol          VARCHAR(20)     NOT NULL,
    side            VARCHAR(10)     NOT NULL,
    order_type      VARCHAR(20)     NOT NULL,
    quantity        DECIMAL(18,8)   NOT NULL,
    limit_price     DECIMAL(18,6),
    stop_price      DECIMAL(18,6),
    filled_quantity DECIMAL(18,8)   DEFAULT 0,
    avg_fill_price  DECIMAL(18,6),
    status          VARCHAR(20)     NOT NULL,
    created_at      TIMESTAMPTZ     DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX idx_orders_strategy ON orders (strategy_id);
CREATE INDEX idx_orders_status ON orders (status);
CREATE INDEX idx_orders_created ON orders (created_at DESC);

-- Fills table
CREATE TABLE fills (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID            REFERENCES orders(id),
    strategy_id     VARCHAR(50)     NOT NULL,
    symbol          VARCHAR(20)     NOT NULL,
    side            VARCHAR(10)     NOT NULL,
    quantity        DECIMAL(18,8)   NOT NULL,
    price           DECIMAL(18,6)   NOT NULL,
    commission      DECIMAL(18,4)   DEFAULT 0,
    filled_at       TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX idx_fills_order ON fills (order_id);
CREATE INDEX idx_fills_strategy ON fills (strategy_id);
CREATE INDEX idx_fills_filled ON fills (filled_at DESC);

-- Migration: Create strategy_state table for persisting runtime strategy state
-- This table tracks whether each strategy is enabled/disabled across restarts

CREATE TABLE IF NOT EXISTS strategy_state (
    strategy_id     VARCHAR(50) PRIMARY KEY,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Index for quick lookups by enabled status
CREATE INDEX IF NOT EXISTS idx_strategy_state_enabled ON strategy_state(enabled);

-- Trigger to auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_strategy_state_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_strategy_state_updated ON strategy_state;
CREATE TRIGGER trigger_strategy_state_updated
    BEFORE UPDATE ON strategy_state
    FOR EACH ROW
    EXECUTE FUNCTION update_strategy_state_timestamp();

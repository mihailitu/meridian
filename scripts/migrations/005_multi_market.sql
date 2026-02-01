-- Multi-market support migration
-- Adds market field to bars table for market-specific data

-- Add market column to bars table with default 'us'
ALTER TABLE bars ADD COLUMN IF NOT EXISTS market VARCHAR(20) DEFAULT 'us';

-- Create index for market-based queries
CREATE INDEX IF NOT EXISTS idx_bars_market ON bars(market);

-- Create composite index for market + symbol queries
CREATE INDEX IF NOT EXISTS idx_bars_market_symbol ON bars(market, symbol);

-- Create composite index for market + interval queries
CREATE INDEX IF NOT EXISTS idx_bars_market_interval ON bars(market, interval);

-- Update the unique constraint to include market
-- Note: This requires dropping and recreating the constraint
-- First check if the old constraint exists and drop it
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'bars_symbol_interval_time_key'
    ) THEN
        ALTER TABLE bars DROP CONSTRAINT bars_symbol_interval_time_key;
    END IF;
END $$;

-- Create new unique constraint including market
ALTER TABLE bars ADD CONSTRAINT bars_market_symbol_interval_time_key
    UNIQUE (market, symbol, interval, time);

-- Migration: Add regime tracking columns to bars table and create regime_history table
-- This migration adds market regime detection fields for trend and volatility analysis

-- Add regime columns to existing bars table (optional, for caching)
ALTER TABLE bars ADD COLUMN IF NOT EXISTS regime VARCHAR(20);
ALTER TABLE bars ADD COLUMN IF NOT EXISTS trend VARCHAR(20);
ALTER TABLE bars ADD COLUMN IF NOT EXISTS volatility VARCHAR(20);
ALTER TABLE bars ADD COLUMN IF NOT EXISTS trend_strength DECIMAL(5,2);
ALTER TABLE bars ADD COLUMN IF NOT EXISTS volatility_percentile DECIMAL(5,2);

-- Create index for regime queries
CREATE INDEX IF NOT EXISTS idx_bars_regime ON bars(symbol, interval, regime);
CREATE INDEX IF NOT EXISTS idx_bars_trend ON bars(symbol, interval, trend);

-- Create regime_history table for tracking regime changes over time
CREATE TABLE IF NOT EXISTS regime_history (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    interval VARCHAR(10) NOT NULL,
    regime VARCHAR(20) NOT NULL,
    trend VARCHAR(20) NOT NULL,
    volatility VARCHAR(20) NOT NULL,
    trend_strength DECIMAL(5,2),
    volatility_percentile DECIMAL(5,2),
    atr_ratio DECIMAL(8,4),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    duration_minutes INTEGER,
    CONSTRAINT regime_history_unique UNIQUE (symbol, interval, started_at)
);

-- Create indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_regime_history_symbol_interval
    ON regime_history(symbol, interval);
CREATE INDEX IF NOT EXISTS idx_regime_history_started_at
    ON regime_history(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_regime_history_regime
    ON regime_history(regime);

-- Add comments for documentation
COMMENT ON COLUMN bars.regime IS 'Market regime: trending_up, trending_down, ranging_quiet, ranging_volatile, breakout, breakdown';
COMMENT ON COLUMN bars.trend IS 'Trend direction: bullish, bearish, neutral';
COMMENT ON COLUMN bars.volatility IS 'Volatility state: low, normal, high, extreme';
COMMENT ON COLUMN bars.trend_strength IS 'Trend strength score 0-100';
COMMENT ON COLUMN bars.volatility_percentile IS 'Volatility percentile 0-100';

COMMENT ON TABLE regime_history IS 'Historical record of regime transitions for analysis';

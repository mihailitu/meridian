-- ORPHANED (phase 4, 2026-07-03): the ML layer was removed (see docs/phase4-platform-pivot.md iteration 3). Tables remain for any DBs that applied this migration; nothing reads or writes them.
-- ML models migration
-- Stores ML model metadata and predictions

-- ML models table
CREATE TABLE IF NOT EXISTS ml_models (
    id SERIAL PRIMARY KEY,
    model_id VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    model_type VARCHAR(50) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    interval VARCHAR(10) NOT NULL DEFAULT '1m',
    config JSONB DEFAULT '{}',
    weights JSONB DEFAULT '{}',
    feature_importance JSONB DEFAULT '{}',
    train_samples INTEGER DEFAULT 0,
    accuracy DOUBLE PRECISION DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_trained TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ml_models_symbol ON ml_models(symbol);
CREATE INDEX IF NOT EXISTS idx_ml_models_active ON ml_models(is_active);

-- ML predictions table
CREATE TABLE IF NOT EXISTS ml_predictions (
    id SERIAL PRIMARY KEY,
    model_id VARCHAR(50) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    direction VARCHAR(20) NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    predicted_return DOUBLE PRECISION,
    features JSONB DEFAULT '{}',
    actual_return DOUBLE PRECISION,
    was_correct BOOLEAN,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Convert to hypertable for time-series queries
SELECT create_hypertable('ml_predictions', 'created_at', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_ml_predictions_model ON ml_predictions(model_id);
CREATE INDEX IF NOT EXISTS idx_ml_predictions_symbol ON ml_predictions(symbol);
CREATE INDEX IF NOT EXISTS idx_ml_predictions_time ON ml_predictions(created_at DESC);

-- ML training runs table
CREATE TABLE IF NOT EXISTS ml_training_runs (
    id SERIAL PRIMARY KEY,
    model_id VARCHAR(50) NOT NULL,
    success BOOLEAN NOT NULL,
    train_samples INTEGER NOT NULL,
    test_samples INTEGER NOT NULL,
    train_accuracy DOUBLE PRECISION NOT NULL,
    test_accuracy DOUBLE PRECISION NOT NULL,
    training_time_seconds DOUBLE PRECISION NOT NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ml_training_runs_model ON ml_training_runs(model_id);
CREATE INDEX IF NOT EXISTS idx_ml_training_runs_time ON ml_training_runs(created_at DESC);

-- Retention policy: keep predictions for 30 days
-- SELECT add_retention_policy('ml_predictions', INTERVAL '30 days', if_not_exists => TRUE);

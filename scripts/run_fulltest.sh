#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

.venv/bin/python -m axtrade.fulltest run \
    --start 2025-08-01 \
    --end 2026-02-01 \
    --universe sp500 \
    --capital 100000 \
    --strategies momentum mean_reversion multi_timeframe pairs ml_prediction \
    --output-dir data/fulltest_results \
    --redis-db 2 \
    --db-name fulltestdb \
    --log-level WARNING

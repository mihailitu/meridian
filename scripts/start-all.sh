#!/bin/bash

# Start all axtrade services in background with logging

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
VENV="$PROJECT_DIR/.venv/bin/python"

# Create logs directory
mkdir -p "$LOG_DIR"

# Timestamp for log files
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "Starting axtrade services..."
echo "Logs will be written to: $LOG_DIR"

# Start infrastructure if not running
if ! docker compose -f "$PROJECT_DIR/docker-compose.yml" ps --status running | grep -q redis; then
    echo "Starting infrastructure (Redis + TimescaleDB)..."
    docker compose -f "$PROJECT_DIR/docker-compose.yml" up -d
    sleep 2
fi

# Start Gateway
echo "Starting Gateway..."
$VENV -m axtrade.gateway > "$LOG_DIR/gateway_$TIMESTAMP.log" 2>&1 &
echo $! > "$LOG_DIR/gateway.pid"
echo "  PID: $(cat $LOG_DIR/gateway.pid)"

# Start Aggregator
echo "Starting Aggregator..."
$VENV -m axtrade.aggregator > "$LOG_DIR/aggregator_$TIMESTAMP.log" 2>&1 &
echo $! > "$LOG_DIR/aggregator.pid"
echo "  PID: $(cat $LOG_DIR/aggregator.pid)"

# Start Strategy Runner
echo "Starting Strategy Runner..."
$VENV -m axtrade.strategies > "$LOG_DIR/strategy_$TIMESTAMP.log" 2>&1 &
echo $! > "$LOG_DIR/strategy.pid"
echo "  PID: $(cat $LOG_DIR/strategy.pid)"

# Start API
echo "Starting API..."
$VENV -m axtrade.api.app > "$LOG_DIR/api_$TIMESTAMP.log" 2>&1 &
echo $! > "$LOG_DIR/api.pid"
echo "  PID: $(cat $LOG_DIR/api.pid)"

echo ""
echo "All services started!"
echo ""
echo "Dashboard: http://localhost:8000"
echo ""
echo "View logs:"
echo "  tail -f $LOG_DIR/gateway_$TIMESTAMP.log"
echo "  tail -f $LOG_DIR/aggregator_$TIMESTAMP.log"
echo "  tail -f $LOG_DIR/strategy_$TIMESTAMP.log"
echo "  tail -f $LOG_DIR/api_$TIMESTAMP.log"
echo ""
echo "Stop all: ./scripts/stop-all.sh"

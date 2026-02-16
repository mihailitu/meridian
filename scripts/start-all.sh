#!/bin/bash

# Start all axtrade services in background with logging
# Each service logs to its own file in logs/ with daily rotation

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
VENV="$PROJECT_DIR/.venv/bin/python"

# Create logs directory
mkdir -p "$LOG_DIR"

echo "Starting axtrade services..."
echo "Logs will be written to: $LOG_DIR"

# Start infrastructure if not running
if ! docker compose -f "$PROJECT_DIR/docker-compose.yml" ps --status running | grep -q redis; then
    echo "Starting infrastructure (Redis + TimescaleDB)..."
    docker compose -f "$PROJECT_DIR/docker-compose.yml" up -d
    sleep 2
fi

# Start Gateway (logs to logs/gateway.log with daily rotation)
echo "Starting Gateway..."
$VENV -m axtrade.gateway --adapter alpaca >> "$LOG_DIR/gateway.log" 2>&1 &
echo $! > "$LOG_DIR/gateway.pid"
echo "  PID: $(cat $LOG_DIR/gateway.pid)"

# Start Aggregator (logs to logs/aggregator.log with daily rotation)
echo "Starting Aggregator..."
$VENV -m axtrade.aggregator >> "$LOG_DIR/aggregator.log" 2>&1 &
echo $! > "$LOG_DIR/aggregator.pid"
echo "  PID: $(cat $LOG_DIR/aggregator.pid)"

# Start Strategy Runner (logs to logs/strategy.log with daily rotation)
echo "Starting Strategy Runner..."
$VENV -m axtrade.strategies >> "$LOG_DIR/strategy.log" 2>&1 &
echo $! > "$LOG_DIR/strategy.pid"
echo "  PID: $(cat $LOG_DIR/strategy.pid)"

# Start API (logs to logs/api.log with daily rotation)
echo "Starting API..."
$VENV -m axtrade.api.app >> "$LOG_DIR/api.log" 2>&1 &
echo $! > "$LOG_DIR/api.pid"
echo "  PID: $(cat $LOG_DIR/api.pid)"

echo ""
echo "All services started!"
echo ""
echo "Dashboard: http://localhost:8000"
echo ""
echo "View logs:"
echo "  tail -f $LOG_DIR/gateway.log"
echo "  tail -f $LOG_DIR/aggregator.log"
echo "  tail -f $LOG_DIR/strategy.log"
echo "  tail -f $LOG_DIR/api.log"
echo ""
echo "Stop all: ./scripts/stop-all.sh"

#!/bin/bash

# Check status of all axtrade services

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"

echo "axtrade Service Status"
echo "======================"
echo ""

# Check infrastructure
echo "Infrastructure:"
if docker compose -f "$PROJECT_DIR/docker-compose.yml" ps --status running 2>/dev/null | grep -q redis; then
    echo "  Redis:       running"
else
    echo "  Redis:       stopped"
fi

if docker compose -f "$PROJECT_DIR/docker-compose.yml" ps --status running 2>/dev/null | grep -q timescaledb; then
    echo "  TimescaleDB: running"
else
    echo "  TimescaleDB: stopped"
fi

echo ""
echo "Services:"

for service in gateway aggregator strategy api; do
    PID_FILE="$LOG_DIR/${service}.pid"
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "  $service: running (PID: $PID)"
        else
            echo "  $service: dead (stale PID file)"
        fi
    else
        echo "  $service: stopped"
    fi
done

echo ""
echo "Latest logs in: $LOG_DIR"

#!/bin/bash

# Stop all axtrade services

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"

echo "Stopping axtrade services..."

for service in gateway aggregator strategy api; do
    PID_FILE="$LOG_DIR/${service}.pid"
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "Stopping $service (PID: $PID)..."
            kill "$PID" 2>/dev/null || true
        fi
        rm -f "$PID_FILE"
    fi
done

echo ""
echo "All services stopped."
echo ""
echo "To also stop infrastructure: docker compose down"

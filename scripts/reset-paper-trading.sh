#!/bin/bash

# Reset paper trading data for a fresh start
# Clears: PostgreSQL tables (orders, fills, positions, bars), Redis streams, strategy state

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}=== Paper Trading Reset ===${NC}"
echo ""

# Check if services are running
if pgrep -f "python.*axtrade" > /dev/null; then
    echo -e "${RED}Error: axtrade services are still running.${NC}"
    echo "Please stop them first with: ./scripts/stop-all.sh"
    exit 1
fi

# Database settings (from config/default.yaml)
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-8112}"
DB_NAME="${DB_NAME:-axtrade}"
DB_USER="${DB_USER:-axtrade}"
DB_PASS="${DB_PASS:-axtrade}"

# Redis settings
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-8113}"

echo "Database: $DB_HOST:$DB_PORT/$DB_NAME"
echo "Redis: $REDIS_HOST:$REDIS_PORT"
echo ""

# Confirm unless --force flag is passed
if [[ "$1" != "--force" && "$1" != "-f" ]]; then
    read -p "This will delete ALL trading data. Continue? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
fi

echo ""
echo -e "${YELLOW}Clearing PostgreSQL tables...${NC}"

PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -q <<EOF
-- Clear trading data (order matters due to foreign keys)
TRUNCATE fills CASCADE;
TRUNCATE orders CASCADE;
TRUNCATE positions CASCADE;

-- Clear market data
TRUNCATE bars CASCADE;

-- Clear strategy state if table exists
DO \$\$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'strategy_state') THEN
        TRUNCATE strategy_state CASCADE;
    END IF;
END
\$\$;

-- Reset sequences if any
-- (UUIDs are generated, so no sequences to reset for main tables)

SELECT 'Tables cleared successfully' as status;
EOF

echo -e "${GREEN}PostgreSQL tables cleared.${NC}"
echo ""

echo -e "${YELLOW}Clearing Redis streams...${NC}"

# Delete tick streams
redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" DEL stream:ticks:us > /dev/null

# Delete bar streams
redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" DEL stream:bars:1m:us stream:bars:5m:us stream:bars:15m:us stream:bars:1h:us > /dev/null

# Delete fill streams
redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" DEL stream:fills > /dev/null

# Delete strategy control channel
redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" DEL axtrade:strategy:control > /dev/null

# Clear strategy state keys
redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" DEL \
    axtrade:strategy:state:momentum_us_01 \
    axtrade:strategy:state:mean_rev_01 \
    axtrade:strategy:state:mtf_01 \
    axtrade:strategy:state:pairs_aapl_msft > /dev/null

echo -e "${GREEN}Redis streams cleared.${NC}"
echo ""

echo -e "${GREEN}=== Reset Complete ===${NC}"
echo ""
echo "You can now start fresh with: ./scripts/start-all.sh"
echo "Or run individual services with: make run"

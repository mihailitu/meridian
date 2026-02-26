#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_command() {
    if ! command -v "$1" &> /dev/null; then
        log_error "$1 is not installed"
        return 1
    fi
    return 0
}

check_python_version() {
    local version
    version=$(python3 --version 2>&1 | grep -oP '\d+\.\d+')
    local major minor
    major=$(echo "$version" | cut -d. -f1)
    minor=$(echo "$version" | cut -d. -f2)

    if [ "$major" -lt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -lt 11 ]; }; then
        log_error "Python 3.11+ required, found $version"
        return 1
    fi
    log_info "Python version: $version"
    return 0
}

check_node_version() {
    local version
    version=$(node --version 2>&1 | grep -oP '\d+' | head -1)

    if [ "$version" -lt 18 ]; then
        log_error "Node.js 18+ required, found v$version"
        return 1
    fi
    log_info "Node.js version: $(node --version)"
    return 0
}

wait_for_postgres() {
    local max_attempts=30
    local attempt=1

    log_info "Waiting for TimescaleDB to be ready..."
    while [ $attempt -le $max_attempts ]; do
        if docker exec axtrade-timescaledb pg_isready -U axtrade -d axtrade &> /dev/null; then
            log_info "TimescaleDB is ready"
            return 0
        fi
        sleep 1
        ((attempt++))
    done

    log_error "TimescaleDB failed to start within ${max_attempts}s"
    return 1
}

wait_for_redis() {
    local max_attempts=30
    local attempt=1

    log_info "Waiting for Redis to be ready..."
    while [ $attempt -le $max_attempts ]; do
        if docker exec axtrade-redis redis-cli ping &> /dev/null; then
            log_info "Redis is ready"
            return 0
        fi
        sleep 1
        ((attempt++))
    done

    log_error "Redis failed to start within ${max_attempts}s"
    return 1
}

run_migrations() {
    log_info "Running database migrations..."

    local migrations_dir="$PROJECT_ROOT/scripts/migrations"
    if [ -d "$migrations_dir" ]; then
        for migration in "$migrations_dir"/*.sql; do
            if [ -f "$migration" ]; then
                local filename
                filename=$(basename "$migration")
                log_info "  Applying: $filename"
                docker exec -i axtrade-timescaledb psql -U axtrade -d axtrade < "$migration" 2>/dev/null || true
            fi
        done
    fi

    log_info "Migrations complete"
}

# Header
echo ""
echo "========================================"
echo "  axtrade Setup Script"
echo "========================================"
echo ""

# Check prerequisites
log_info "Checking prerequisites..."

MISSING_DEPS=0

if ! check_command python3; then
    log_error "  Install Python 3.11+: https://www.python.org/downloads/"
    MISSING_DEPS=1
else
    check_python_version || MISSING_DEPS=1
fi

if ! check_command docker; then
    log_error "  Install Docker: https://docs.docker.com/get-docker/"
    MISSING_DEPS=1
else
    log_info "Docker: $(docker --version | grep -oP '\d+\.\d+\.\d+')"
fi

if ! check_command docker-compose && ! docker compose version &> /dev/null; then
    log_error "  Install Docker Compose: https://docs.docker.com/compose/install/"
    MISSING_DEPS=1
else
    log_info "Docker Compose: available"
fi

if ! check_command node; then
    log_warn "  Node.js not found - frontend setup will be skipped"
    log_warn "  Install Node.js 18+: https://nodejs.org/"
    SKIP_FRONTEND=1
else
    check_node_version || SKIP_FRONTEND=1
fi

if ! check_command npm; then
    log_warn "  npm not found - frontend setup will be skipped"
    SKIP_FRONTEND=1
fi

if [ $MISSING_DEPS -eq 1 ]; then
    log_error "Missing required dependencies. Please install them and re-run this script."
    exit 1
fi

echo ""

# Step 1: Python environment
log_info "Setting up Python virtual environment..."

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    log_info "Created .venv"
else
    log_info ".venv already exists"
fi

source .venv/bin/activate
log_info "Activated virtual environment"

log_info "Installing Python dependencies..."
pip install --upgrade pip --quiet
pip install -e ".[dev]" --quiet
log_info "Python dependencies installed"

echo ""

# Step 2: Infrastructure
log_info "Starting infrastructure..."

# Check if Docker daemon is running
if ! docker info &> /dev/null; then
    log_error "Docker daemon is not running. Please start Docker and re-run this script."
    exit 1
fi

# Start infrastructure using docker compose
if docker compose version &> /dev/null; then
    docker compose up -d
else
    docker-compose up -d
fi

wait_for_redis
wait_for_postgres

echo ""

# Step 3: Database migrations
run_migrations

echo ""

# Step 4: Frontend setup
if [ "${SKIP_FRONTEND:-0}" != "1" ]; then
    log_info "Setting up frontend..."

    FRONTEND_DIR="$PROJECT_ROOT/src/axtrade/web/ui"
    if [ -d "$FRONTEND_DIR" ]; then
        cd "$FRONTEND_DIR"

        if [ ! -d "node_modules" ]; then
            log_info "Installing npm dependencies..."
            npm install --silent
        else
            log_info "node_modules already exists"
        fi

        # Build for production (served by API)
        log_info "Building frontend for production..."
        npm run build

        cd "$PROJECT_ROOT"
        log_info "Frontend built and will be served by API at http://localhost:8110"
    else
        log_warn "Frontend directory not found at $FRONTEND_DIR"
    fi
else
    log_warn "Skipping frontend setup (Node.js/npm not available)"
    log_warn "Frontend will not be available. Install Node.js 18+ and re-run setup."
fi

echo ""

# Step 5: Create logs directory
mkdir -p "$PROJECT_ROOT/logs"

# Done
echo "========================================"
echo -e "${GREEN}  Setup Complete${NC}"
echo "========================================"
echo ""
echo "Next steps:"
echo ""
echo "  1. Start all services:"
echo "     ./scripts/start-all.sh"
echo ""
echo "  2. Or start services individually:"
echo "     make run              # Gateway (mock data)"
echo "     make run-aggregator   # Bar aggregator"
echo "     make run-strategy     # Strategy runner"
echo "     make run-api          # Web API + frontend"
echo ""
echo "  3. Access the dashboard:"
echo "     http://localhost:8110"
echo ""
echo "  4. Check system status:"
echo "     ./scripts/status.sh"
echo ""
echo "  5. For frontend development (hot reload):"
echo "     cd src/axtrade/web/ui && npm run dev"
echo "     (runs at http://localhost:5173, proxies API calls)"
echo ""

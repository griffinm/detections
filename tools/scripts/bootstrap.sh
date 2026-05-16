#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; exit 1; }

echo "=== video-detection bootstrap ==="

# Check prerequisites
command -v node >/dev/null 2>&1 || fail "Node.js not found. Install Node 20 LTS."
node_version=$(node -v | sed 's/v//' | cut -d. -f1)
[ "$node_version" -ge 20 ] || fail "Node 20+ required, found $(node -v)"
ok "Node $(node -v)"

command -v pnpm >/dev/null 2>&1 || fail "pnpm not found. Install: npm i -g pnpm"
ok "pnpm $(pnpm -v)"

command -v uv >/dev/null 2>&1 || fail "uv not found. Install: curl -Lsf https://astral.sh/uv/install.sh | sh"
ok "uv $(uv --version)"

command -v docker >/dev/null 2>&1 || fail "Docker not found. Install Docker Engine 25+."
ok "docker $(docker --version | cut -d' ' -f3 | tr -d ',')"

# Install JS deps
echo ""
echo "Installing JS dependencies..."
pnpm install
ok "pnpm install"

# Sync Python venvs
echo ""
echo "Syncing Python environments..."
for project in libs/python/settings libs/python/db libs/python/tasks libs/python/ml \
               apps/api apps/worker apps/ingest-watcher; do
  if [ -f "$project/pyproject.toml" ]; then
    echo "  Syncing $project..."
    (cd "$project" && uv sync --no-dev) || warn "uv sync failed for $project (non-fatal)"
  fi
done
ok "Python environments synced"

# Pre-commit
if command -v pre-commit >/dev/null 2>&1; then
  pre-commit install
  ok "pre-commit hooks installed"
else
  warn "pre-commit not found, skipping hook installation"
fi

# Start data services
echo ""
echo "Starting Postgres and Redis..."
docker compose -f docker/docker-compose.yml up -d postgres redis

echo "Waiting for Postgres to be healthy..."
max_attempts=30
attempt=0
while ! docker compose -f docker/docker-compose.yml exec -T postgres pg_isready -U vd >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  [ "$attempt" -ge "$max_attempts" ] && fail "Postgres did not become healthy after ${max_attempts}s"
  sleep 1
done
ok "Postgres healthy"

echo "Waiting for Redis..."
attempt=0
while ! docker compose -f docker/docker-compose.yml exec -T redis redis-cli ping >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  [ "$attempt" -ge "$max_attempts" ] && fail "Redis did not respond after ${max_attempts}s"
  sleep 1
done
ok "Redis healthy"

# Run migrations
echo ""
echo "Applying database migrations..."
(cd libs/python/db && uv run alembic upgrade head)
ok "Migrations applied"

echo ""
echo -e "${GREEN}=== Bootstrap complete! ===${NC}"
echo ""
echo "Start dev services in separate terminals:"
echo "  nx run api:serve"
echo "  nx run worker:serve"
echo "  nx run ingest-watcher:serve"
echo "  nx run web:serve"
echo ""
echo "Health check:"
echo "  curl http://localhost:8000/api/system/health"

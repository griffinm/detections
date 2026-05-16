#!/usr/bin/env bash
# Start the whole app for local development: infra in Docker + all dev servers.
# Postgres/Redis are left running on exit; the four app servers stop with Ctrl-C.
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; exit 1; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

COMPOSE="docker compose -f docker/docker-compose.yml"

echo "=== video-detection dev ==="

[ -f .env ] || fail ".env not found — run ./tools/scripts/bootstrap.sh first."

# Infra only: Postgres + Redis. Workers/watcher run as dev servers below.
echo ""
echo "Starting Postgres and Redis..."
$COMPOSE up -d postgres redis

echo "Waiting for Postgres..."
attempt=0
while ! $COMPOSE exec -T postgres pg_isready -U vd >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  [ "$attempt" -ge 30 ] && fail "Postgres did not become healthy."
  sleep 1
done
ok "Postgres healthy"

echo "Waiting for Redis..."
attempt=0
while ! $COMPOSE exec -T redis redis-cli ping >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  [ "$attempt" -ge 30 ] && fail "Redis did not respond."
  sleep 1
done
ok "Redis healthy"

# Migrations are idempotent — safe to apply on every dev start.
echo ""
echo "Applying database migrations..."
(cd libs/python/db && uv run alembic upgrade head)
ok "Migrations applied"

echo ""
echo "Starting dev servers (api, worker, ingest-watcher, web)..."
echo "  api  :8000   web  :5173   flower not started (run via docker compose if needed)"
echo "  worker consumes the cpu queue only — run 'pnpm gpu' in another terminal for GPU tasks"
echo "Press Ctrl-C to stop the dev servers. Postgres/Redis keep running."
echo ""

# nx run-many supervises the four long-running processes and forwards Ctrl-C.
exec npx nx run-many \
  -t serve \
  --projects=api,worker,ingest-watcher,web \
  --parallel=4 \
  --output-style=stream

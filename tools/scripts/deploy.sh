#!/usr/bin/env bash
# Re-deploy to the `layla` server: rsync repo source up, rebuild images, restart.
# This app has no CI/registry — images are built on the server. See
# plans/02-infra-and-config.md (§Production deployment).
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; exit 1; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

SSH_HOST="${VD_DEPLOY_HOST:-layla}"
REMOTE_SRC="/home/griffin/video-detections"
# The server includes this compose file from ~/docker/docker-compose.yml.
REMOTE_COMPOSE="\$HOME/docker/compose/video-detections.yml"
COMPOSE_REL="compose/video-detections.yml"

cd "$ROOT"

# data/ is bind-mounted state on the server — never sync over it.
warn "Syncing source to ${SSH_HOST}:${REMOTE_SRC}"
rsync -az --delete \
  --exclude node_modules --exclude .venv --exclude data --exclude .git \
  ./ "${SSH_HOST}:${REMOTE_SRC}/"
ok "Source synced"

warn "Installing compose file"
scp docker/server-compose.yml "${SSH_HOST}:${REMOTE_COMPOSE}"
ok "Compose file installed"

warn "Building images + restarting on ${SSH_HOST} (this can take a while)"
# api container runs `alembic upgrade head` on start — no manual migration step.
# Services pin explicit container_name:, which is a global (non-project-scoped)
# namespace — a stale or differently-projected container makes `up` fail with
# "Conflicting container name". `down` clears the normal case; the `docker rm`
# fallback catches containers left under a different compose project name.
ssh "$SSH_HOST" "cd \$HOME/docker && \
  docker compose -f ${COMPOSE_REL} build && \
  docker compose -f ${COMPOSE_REL} down --remove-orphans && \
  { docker rm -f vd-api vd-web vd-worker-cpu vd-worker-gpu vd-ingest-watcher vd-flower 2>/dev/null || true; } && \
  docker compose -f ${COMPOSE_REL} up -d"
ok "Deploy complete — web :10800  api :10801  flower :10802"

#!/usr/bin/env bash
# Build the service images locally, push them to the private registry, and
# point the `layla` server at the new tags. Mirrors the deploy pattern used
# by sibling repos (see ../unifi-protect/push-to-docker.sh). No on-server
# build, no source rsync — `data/` on the server is untouched.
#
# Prereqs (one-time, on layla):
#   1. ~/docker/compose/video-detections.yml installed from docker/server-compose.yml
#   2. ~/docker/.env contains VD_API_IMAGE, VD_WEB_IMAGE, VD_WORKER_IMAGE,
#      VD_WATCHER_IMAGE (initial values don't matter — the first deploy
#      rewrites them) and VIDEO_DETECTION_DB_PASSWORD.
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

SSH_HOST="${VD_DEPLOY_HOST:-layla}"
REGISTRY="${VD_REGISTRY:-nas.malfin.com:10100}"

docker info > /dev/null 2>&1 || fail "Docker is not running"

GIT_HASH=$(git rev-parse --short HEAD)
API_IMAGE="${REGISTRY}/vd-api:${GIT_HASH}"
WEB_IMAGE="${REGISTRY}/vd-web:${GIT_HASH}"
WORKER_IMAGE="${REGISTRY}/vd-worker:${GIT_HASH}"
WATCHER_IMAGE="${REGISTRY}/vd-ingest-watcher:${GIT_HASH}"

warn "Building images for ${GIT_HASH}"
docker build -t "$API_IMAGE"     -f docker/api/Dockerfile     .
ok "api built"
docker build -t "$WEB_IMAGE"     -f docker/web/Dockerfile     .
ok "web built"
# worker-cpu and worker-gpu share this image — different command/runtime only.
docker build -t "$WORKER_IMAGE"  -f docker/worker/Dockerfile  --target gpu .
ok "worker built"
docker build -t "$WATCHER_IMAGE" -f docker/watcher/Dockerfile .
ok "watcher built"

warn "Pushing to ${REGISTRY}"
docker push "$API_IMAGE"     && ok "api pushed"
docker push "$WEB_IMAGE"     && ok "web pushed"
docker push "$WORKER_IMAGE"  && ok "worker pushed"
docker push "$WATCHER_IMAGE" && ok "watcher pushed"

warn "Updating image tags in ${SSH_HOST}:~/docker/.env"
ssh "$SSH_HOST" "
  set -e
  sed -i 's|^VD_API_IMAGE=.*|VD_API_IMAGE=${API_IMAGE}|'         ~/docker/.env
  sed -i 's|^VD_WEB_IMAGE=.*|VD_WEB_IMAGE=${WEB_IMAGE}|'         ~/docker/.env
  sed -i 's|^VD_WORKER_IMAGE=.*|VD_WORKER_IMAGE=${WORKER_IMAGE}|' ~/docker/.env
  sed -i 's|^VD_WATCHER_IMAGE=.*|VD_WATCHER_IMAGE=${WATCHER_IMAGE}|' ~/docker/.env
"
ok "Image tags updated"

warn "Pulling images + restarting containers on ${SSH_HOST}"
# `--project-directory \$HOME/docker` pins the .env lookup and the compose
# project name to ~/docker (matching the include-based runs); without it,
# Compose treats compose/ as the project dir and fails on the missing .env.
# `unset DOCKER_HOST` mirrors the sibling repo — needed when the remote
# shell inherits a docker context that points elsewhere.
ssh "$SSH_HOST" "cd \$HOME/docker && unset DOCKER_HOST && \
  docker compose --project-directory \$HOME/docker -f compose/video-detections.yml \
    up -d --pull always vd-api vd-web vd-worker-cpu vd-worker-gpu vd-ingest-watcher vd-flower"
ok "Deploy complete — web :10800  api :10801  flower :10802"

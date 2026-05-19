# video-detection

Self-hosted application that ingests video clips, extracts frames, detects objects (YOLO), recognizes faces (InsightFace), and tracks accuracy over time via human review.

Single user · single GPU · single host.

## Prerequisites

- Ubuntu 22.04 / 24.04 (or WSL2)
- NVIDIA driver ≥ 535 (CUDA 12.x)
- Docker Engine 25+ with Compose plugin
- NVIDIA Container Toolkit (`nvidia-ctk`)
- Node 20 LTS + pnpm
- `uv` (Python package manager)

Verify GPU access in Docker:
```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

## Quick start

```bash
git clone <repo-url>
cd video-detection
./tools/scripts/bootstrap.sh
```

## Running dev services

Start everything (Postgres + Redis in Docker, then all four dev servers) with:

```bash
pnpm dev   # or: ./tools/scripts/dev.sh
```

Ctrl-C stops the dev servers; Postgres/Redis keep running.

To run servers individually, open separate terminals:

```bash
nx run api:serve            # FastAPI on :8000
nx run worker:serve         # Celery worker
nx run ingest-watcher:serve # Folder watcher (inbox/)
nx run web:serve            # Vite dev server on :5173
```

## Project structure

```
apps/
  api/             FastAPI backend
  worker/          Celery worker (CPU + GPU tasks)
  ingest-watcher/  Watchdog folder monitor
  web/             React + Vite frontend
libs/
  python/
    settings/      Shared pydantic-settings config
    db/            SQLAlchemy models + Alembic migrations
    tasks/         Celery task contracts
    ml/            Detector / embedder / trainer code
  ts/
    api-client/    Generated OpenAPI client
    ui/            Shared shadcn components
    theme/         Tailwind preset + tokens
docker/
  docker-compose.yml   Postgres, Redis, workers, watcher
  worker/Dockerfile    Multi-stage CPU/GPU worker
data/
  videos/          inbox/ processed/ failed/
  frames/          Extracted JPEGs per clip
  models/          YOLO, InsightFace, classifier weights
specs/             Architecture decisions (source of truth)
```

## Quality gate

```bash
nx run-many -t lint typecheck test
```

## Health check

```bash
curl http://localhost:8000/api/system/health
```

## Monitoring

- **Metrics page** — `/metrics` in the web app: class-accuracy over time per
  model version, per-class precision/recall, a calibration reliability
  diagram, and recent reassignments.
- **Flower** — Celery queue inspection (queue depth, workers, task history) at
  [http://localhost:5555](http://localhost:5555) once `docker compose up` is
  running.

## Operations

- **System page** — `/system/disk` in the web app: per-directory disk usage and
  a "purge frames older than N days" tool. Clips can be deleted from a clip's
  detail page (removes frames, detections, and files).
- **Settings page** — `/settings`: edit processing/training tunables and
  retention flags. Changes are stored in the database and take effect on the
  next worker job — no restart needed.
- **Runbook** — [`docs/runbook.md`](docs/runbook.md) covers starting/stopping
  services, backups, disk management, and a troubleshooting table.

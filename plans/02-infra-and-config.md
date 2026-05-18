# 02 — Infrastructure & Configuration

## Goals

- One-command bring-up of all data + worker services in docker-compose.
- The worker container has GPU access via NVIDIA Container Toolkit.
- Configuration is centralized in `.env` and surfaced via `pydantic-settings`.
- Folders for videos, frames, and model weights are bind-mounted, not stored
  in volumes, so the host can drop files in and the user can inspect outputs.

## Host prerequisites

Ubuntu 22.04 / 24.04 reference. Document in README:

1. **NVIDIA driver** (matched to CUDA 12.x — Ultralytics 8.3+ targets CUDA 12).
2. **Docker Engine 25+** with `compose` plugin.
3. **NVIDIA Container Toolkit**: `nvidia-ctk` installed; `/etc/docker/daemon.json`
   has `"default-runtime": "nvidia"` (or services declare it per the compose
   schema below). Verify with `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi`.
4. **`uv` installed** (host tools).

## docker-compose services

`docker/docker-compose.yml` is the single compose file. (An earlier
`docker-compose.override.yml` was removed: the launch scripts pass an explicit
`-f`, which disables compose's auto-merge of the override, so it was dead
config. The container-network DB/broker URLs it carried now live in the base
file's per-service `environment:` blocks, overriding the `localhost` defaults
in `.env`.)

The same `environment:` blocks **must** also override every `VD_*_DIR` path.
`.env` is shared with host-run dev processes, so it carries host-absolute
paths (`/home/.../data/frames`); inside the containers those directories are
bind-mounted at `/data/...`. A worker that inherits the host path resolves
frames/models to a non-existent directory — and `vd.detect_frame_batch`
silently treats a missing JPEG as an object-free frame, so the mismatch
surfaces as clips that "process" with zero detections, not as an error.

```yaml
# docker/docker-compose.yml (abridged)
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: vd
      POSTGRES_PASSWORD: vd
      POSTGRES_DB: video_detection
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./postgres/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U vd"]
      interval: 5s

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s

  worker-cpu:
    build:
      context: ../
      dockerfile: docker/worker/Dockerfile
      target: cpu
    env_file: ../.env
    volumes:
      - ../data/videos:/data/videos
      - ../data/frames:/data/frames
      - ../data/models:/data/models
    command: celery -A worker.app worker -Q cpu -c 2 --loglevel=INFO
    depends_on:
      postgres: { condition: service_healthy }
      redis:    { condition: service_healthy }

  worker-gpu:
    build:
      context: ../
      dockerfile: docker/worker/Dockerfile
      target: gpu
    env_file: ../.env
    runtime: nvidia                # if default-runtime is not nvidia
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    volumes:
      - ../data/videos:/data/videos
      - ../data/frames:/data/frames
      - ../data/models:/data/models
    command: celery -A worker.app worker -Q gpu,train -c 1 --loglevel=INFO
    depends_on:
      postgres: { condition: service_healthy }
      redis:    { condition: service_healthy }

  ingest-watcher:
    build:
      context: ../
      dockerfile: docker/watcher/Dockerfile
    env_file: ../.env
    volumes:
      - ../data/videos:/data/videos
    depends_on:
      redis: { condition: service_healthy }

  flower:                          # optional: Celery UI
    image: mher/flower:2.0
    command: celery --broker=redis://redis:6379/0 flower --port=5555
    ports: ["5555:5555"]
    depends_on: [redis]

volumes:
  pgdata: {}
```

The `api` service is intentionally NOT in `docker/docker-compose.yml` — for
local dev we run it on the host (`nx run api:serve`) for fast iteration.
**Production is different** — see below.

## Production deployment (server `layla`)

The app is deployed to a 24/7 home server (`ssh layla`) that already runs an
unrelated multi-app docker-compose stack under `~/docker`. We reuse that
stack's shared services rather than duplicating them.

- **Compose layout.** `docker/server-compose.yml` (this repo) is installed on
  the server as `~/docker/compose/video-detections.yml` and pulled in by the
  `include:` list in `~/docker/docker-compose.yml`. All services join the
  shared external `prod` network.
- **Shared infra, not duplicated.** No postgres/redis of our own. We use the
  stack's shared `postgres` and `redis` containers (`infra.yml`). The shared
  Postgres image was swapped `postgres:17` → `pgvector/pgvector:pg17` (data
  volume is compatible — same PG 17, the image only adds the `vector`
  extension). DB `video_detection`, role `video_detection_user`. Redis uses
  logical db **5** (`redis://redis:6379/5`) to avoid colliding with other
  apps' keyspaces.
- **API + web ARE containerized here**, unlike local dev — `docker/api/Dockerfile`
  (uvicorn; runs `alembic upgrade head` on start) and `docker/web/Dockerfile`
  (Vite build → nginx). The web nginx (`docker/web/nginx.conf`) proxies `/api`
  and `/files` to the `vd-api` container, so the SPA's same-origin relative
  calls work without CORS.
- **Host ports** (LAN only): web `10800`, api `10801`, flower `10802`.
- **Data** is bind-mounted under `/home/griffin/video-detections/data` on the
  server (same layout as below). The watched inbox is
  `/home/griffin/video-detections/data/videos/inbox`.
- **Images are built on the server** (`docker compose -f
  compose/video-detections.yml build`) — this app has no CI/registry pipeline,
  unlike the other apps in the stack. Redeploy = rsync repo source up, rebuild,
  `docker compose up -d`.

## Worker Dockerfile (multi-stage)

```dockerfile
# docker/worker/Dockerfile
# CUDA 12.8: the worker GPU is Blackwell (sm_120); 12.4 torch wheels carry no
# kernels for that arch and abort at inference with "no kernel image".
FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04 AS base
# Build-only: keep apt non-interactive (tzdata otherwise prompts for a timezone).
ARG DEBIAN_FRONTEND=noninteractive
# Ubuntu 22.04 ships Python 3.10; 3.12 comes from the deadsnakes PPA.
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3.12-venv python3-pip ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv
WORKDIR /app

FROM base AS gpu
# Two-phase sync: install heavy third-party deps from manifests only, then
# editable-link the local libs after their source is copied. See "build
# cache" note below.
COPY apps/worker/pyproject.toml apps/worker/uv.lock /app/apps/worker/
COPY libs/python/*/pyproject.toml /app/libs/python/<lib>/   # manifests only
RUN cd /app/apps/worker && uv sync --frozen --no-dev --extra gpu \
    --no-install-package vd-settings --no-install-package vd-db \
    --no-install-package vd-tasks --no-install-package vd-ml
COPY libs/python /app/libs/python
COPY apps/worker /app/apps/worker
RUN cd /app/apps/worker && uv sync --frozen --no-dev --extra gpu
# Put the venv on PATH so the compose `command:` can invoke `celery` directly.
ENV PATH=/app/apps/worker/.venv/bin:$PATH
ENV PYTHONPATH=/app/apps/worker/src
CMD ["celery", "-A", "worker.app", "worker"]

FROM base AS cpu
# CPU image uses cpu torch wheels via uv extras (`--extra cpu`); same
# two-phase sync as gpu.
COPY apps/worker/pyproject.toml apps/worker/uv.lock /app/apps/worker/
COPY libs/python/*/pyproject.toml /app/libs/python/<lib>/
RUN cd /app/apps/worker && uv sync --frozen --no-dev --extra cpu \
    --no-install-package vd-settings --no-install-package vd-db \
    --no-install-package vd-tasks --no-install-package vd-ml
COPY libs/python /app/libs/python
COPY apps/worker /app/apps/worker
RUN cd /app/apps/worker && uv sync --frozen --no-dev --extra cpu
ENV PATH=/app/apps/worker/.venv/bin:$PATH
ENV PYTHONPATH=/app/apps/worker/src
CMD ["celery", "-A", "worker.app", "worker"]
```

> A repo-root `.dockerignore` excludes `**/.venv` (and caches, `data/`, `.git`):
> without it the `COPY apps/worker` line would overlay the host's virtualenv —
> built for a different Python/OS — onto the image's freshly synced one.

Notes:
- The `gpu` worker handles `gpu` and `train` queues; the `cpu` worker handles
  `cpu` (ingest, ffmpeg, DB-bound work). This keeps the single GPU from being
  saturated by ffmpeg jobs.
- ffmpeg is installed system-wide and called via subprocess. Frame extraction
  is CPU-bound; running it on the `cpu` worker keeps GPU free for inference.
- The `gpu`/`cpu` distinction is real, not just an image tag: generic PyPI
  `torch` ships no CUDA kernels. `apps/worker/pyproject.toml` pins `torch`
  (and `torchvision`) to `download.pytorch.org/whl/cu128` under the `gpu`
  extra and `/whl/cpu` under the `cpu` extra, via `[[tool.uv.index]]` +
  `[tool.uv.sources]`. The two extras are declared `conflicts` so uv can
  resolve each split. `uv.lock` must be regenerated (`uv lock`) on any change
  to these — the Dockerfiles `COPY uv.lock` and run `uv sync --frozen`.
  **cu128, not cu124:** the worker GPU is Blackwell-class (compute capability
  `sm_120`); the cu124 wheels (torch ≤2.6) contain no `sm_120` kernels and
  fail at the first GPU op with `CUDA error: no kernel image is available`.
  cu128 + `torch>=2.7` is the floor for Blackwell. Keep the CUDA base image
  tag (above) in step with the wheel index.
- `insightface` (0.7.3, the only release) publishes just an sdist with a
  Cython/C++ extension built at install time, so the `gpu` Docker stage
  installs `build-essential` + `python3.12-dev`, runs `uv sync`, then purges
  the toolchain in the same layer. The `cpu` stage needs none of this.
- **Build cache:** the local libs (`vd-settings`, `vd-db`, `vd-tasks`,
  `vd-ml`) are editable path deps. Copying their full source *before*
  `uv sync` would invalidate the heavy third-party install layer on every
  lib edit, forcing a full reinstall of torch/ultralytics/insightface — felt
  as a slow `npm run gpu` (which rebuilds via `--build`). So each stage syncs
  in two phases: first install third-party deps from the lib *manifests*
  only (`--no-install-package` skips the local libs, whose source isn't
  present yet); then `COPY libs/python` and run `uv sync` again to
  editable-link them. Only the cheap second sync is invalidated by lib edits.

## Folder layout (bind-mounted)

```
data/
├── videos/
│   ├── inbox/          # drop zone (watched)
│   ├── processed/      # moved here on success
│   └── failed/         # moved here on permanent failure
├── frames/
│   └── <clip_id>/      # frame_0001.jpg, frame_0002.jpg, …
└── models/
    ├── yolo/
    │   ├── base/       # ultralytics base weights (downloaded once)
    │   └── runs/<run_id>/{weights,metrics.json}
    ├── insightface/    # arcface + retinaface weights (buffalo_l pack)
    ├── hf/             # Hugging Face cache — DINOv2 weights
    └── classifiers/
        └── <class_id>/<version>.joblib
```

All paths are configurable via env vars. The defaults are above.

The GPU worker container sets `INSIGHTFACE_HOME=/data/models/insightface` and
`HF_HOME=/data/models/hf` so InsightFace and DINOv2 weights download once onto
the mounted `models/` volume rather than on every container start.

## Configuration (`.env` + pydantic-settings)

A `libs/python/settings` package exposes a `Settings` model loaded once per
process. The .env values are validated, typed, and re-exported.

```python
# libs/python/settings/src/settings.py
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="VD_", extra="ignore")

    # storage
    inbox_dir: Path = Path("/data/videos/inbox")
    processed_dir: Path = Path("/data/videos/processed")
    failed_dir: Path = Path("/data/videos/failed")
    frames_dir: Path = Path("/data/frames")
    models_dir: Path = Path("/data/models")

    # database
    database_url: str = "postgresql+asyncpg://vd:vd@localhost:5432/video_detection"

    # queue
    redis_url: str = "redis://localhost:6379/0"

    # processing
    frame_fps: float = 1.0
    detection_min_confidence: float = 0.25
    subclass_min_confidence: float = 0.55
    frame_jpeg_quality: int = 90
    detect_batch_size: int = 16

    # training
    custom_class_finetune_threshold: int = 100
    subclass_retrain_threshold: int = 25
    yolo_base_model: str = "yolo11l.pt"
    insightface_pack: str = "buffalo_l"

    # delete vs retain
    delete_processed_videos: bool = False       # if true, remove from /processed on cleanup
    delete_frames_without_objects: bool = True  # if true, prune empty frames' files
```

The same `.env` is loaded by both the host-run API and the containerized
worker. The compose file maps it in via `env_file`.

## Env vars (canonical list)

| Var                                | Default                                | Notes                                |
|------------------------------------|----------------------------------------|--------------------------------------|
| `VD_DATABASE_URL`                  | `postgresql+asyncpg://vd:vd@…`         |                                       |
| `VD_REDIS_URL`                     | `redis://localhost:6379/0`             |                                       |
| `VD_INBOX_DIR`                     | `/data/videos/inbox`                   | watched folder                        |
| `VD_FRAMES_DIR`                    | `/data/frames`                         |                                       |
| `VD_MODELS_DIR`                    | `/data/models`                         |                                       |
| `VD_FRAME_FPS`                     | `1.0`                                  | sampling rate                         |
| `VD_DETECTION_MIN_CONFIDENCE`      | `0.25`                                 | "no objects" cutoff                   |
| `VD_SUBCLASS_MIN_CONFIDENCE`       | `0.55`                                 | cosine-sim threshold for kNN          |
| `VD_CUSTOM_CLASS_FINETUNE_THRESHOLD`| `100`                                 | labels needed to trigger fine-tune    |
| `VD_DELETE_FRAMES_WITHOUT_OBJECTS` | `true`                                 | requirement says discard empties      |
| `VD_DETECT_BATCH_SIZE`             | `16`                                   | frames per `vd.detect_frame_batch` task |
| `VD_PRUNE_SIMILAR_FRAMES`          | `true`                                 | enable `vd.dedup_clip_frames` (plan 05) |
| `VD_FRAME_SIMILARITY_THRESHOLD`    | `6`                                    | max pHash Hamming distance for a dup   |

## GPU sanity check

A `nx run worker:gpu-check` target runs:
```python
import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))
from ultralytics import YOLO; YOLO("yolo11n.pt")("ultralytics/assets/bus.jpg", device=0)
```
inside the GPU worker container. This is part of bootstrap verification.

## Backups / data safety

- v1: bind-mounted data is on the host filesystem — user's responsibility to
  back up. Document with a one-liner cron snippet (`pg_dump` + `tar` of
  `data/`).
- v2 (future): a `backup` service in compose that nightly dumps Postgres
  and rsyncs `data/` to a configured destination.

## Open questions

- **NVIDIA Container Toolkit version**: pin to a tested combo
  (driver / CUDA / pytorch / ultralytics) and document it. Suggest:
  driver ≥ 535, CUDA 12.4, PyTorch 2.4+, Ultralytics 8.3+.
- **Disk pressure**: at 1 FPS the frames directory grows quickly. *(Phase 7)*
  The `/system` page shows per-directory usage and runs a "purge frames older
  than N days" tool (`POST /system/purge-frames` → `vd.purge_frames`); see
  `docs/runbook.md` for a cron-able equivalent.

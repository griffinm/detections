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
frames/models to a non-existent directory — and `vd.detect_and_track_clip`
raises loudly on the first missing JPEG so the mismatch surfaces as a
worker failure rather than as clips that "process" with zero detections.

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
  calls work without CORS. The proxy resolves `vd-api` per-request via Docker's
  embedded DNS (`resolver 127.0.0.11`, hostname via a `set` variable) — a bare
  hostname in `proxy_pass` is resolved once at startup and cached, so a
  recreated `vd-api` (new IP) would 502 until nginx reloaded.
- **Host ports** (LAN only): web `10800`, api `10801`, flower `10802`.
- **Data** is bind-mounted from the NAS under
  `/mnt/nas/app-data/video-detections/data` on the server (same layout as
  below). The watched inbox is
  `/mnt/nas/app-data/video-detections/data/videos/inbox`.
- **Images are built locally and pushed to a private registry** at
  `nas.malfin.com:10100`, matching the sibling apps in this stack (see
  `../unifi-protect/push-to-docker.sh`). `tools/scripts/deploy.sh` builds
  `vd-api`, `vd-web`, `vd-worker`, `vd-ingest-watcher` tagged with the
  short git hash, pushes them, rewrites the `VD_*_IMAGE` vars in
  `~/docker/.env`, and runs `docker compose up -d --pull always` on
  `layla`. No source rsync — `data/` on the server is bind-mounted state
  that's already in place. `vd-worker-cpu` and `vd-worker-gpu` share the
  same `VD_WORKER_IMAGE` (built with `--target gpu`); they differ only in
  `command:` and the `runtime: nvidia` / gpu reservation on the gpu
  variant.
- **`--project-directory ~/docker` is required** for the standalone `-f
  compose/video-detections.yml` invocations in `deploy.sh`. Otherwise Compose
  treats `compose/` as the project dir, looks for `.env` in `~/docker/compose/`
  (missing → `VIDEO_DETECTION_DB_PASSWORD` interpolation fails) and names the
  project `compose` instead of `docker`. The `include:`-based runs from the
  parent `docker-compose.yml` are unaffected.

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
  is CPU-bound and runs on the `cpu` worker. Post-extract HEVC compression
  uses `hevc_nvenc` and runs on the `gpu` worker — the Ubuntu apt `ffmpeg`
  build links NVENC dynamically against `libnvidia-encode.so.1`, which the
  Container Toolkit mounts from the host driver, so no custom ffmpeg build
  is required. (NVENC is a dedicated silicon block separate from the CUDA
  cores, so it doesn't fight YOLO for compute.)
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
│   ├── inbox/          # drop zone — watched by ingest-watcher; also the
│   │                   #   target of browser uploads (POST /api/clips/upload)
│   ├── intake/         # external apps write here, then call POST /api/jobs
│   │                   #   — NOT watched; the API call is the sole trigger
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

## External video submission

Two upstream apps (a UniFi Protect motion archiver and a family-video archiver)
feed this system video to be told *who/what is in it*. They run on the same
host and share the `data/` mount, so videos are passed **by path reference, not
over HTTP**:

1. The upstream app writes the file under `intake/` (`VD_INTAKE_DIR`).
2. It calls `POST /api/jobs` with the path plus correlation metadata
   (see spec 04 §Jobs).
3. The API validates the path is inside `VD_INTAKE_DIR`, creates the `clips`
   row, and enqueues `vd.ingest_video` — the same pipeline a watched-folder
   drop runs.
4. On `clip.done`/`clip.failed`, `vd.deliver_callback` POSTs the detection
   result to the job's `callback_url` (spec 05); apps without a webhook poll
   `GET /api/jobs/{id}`.

`intake/` is deliberately **not** watched by `ingest-watcher`: if it were, the
watcher would race the API and create a second, metadata-less `clips` row for
the same file. `inbox/` stays the watched path for manual/ad-hoc drops.

Browser uploads take the `inbox/` path, not the `intake/` one. `POST
/api/clips/upload` (spec 04 §Clips) streams the file into `inbox/` and stops
there — it does **not** create a `clips` row, leaving the watcher as the sole
trigger, so the same anti-double-row rule holds. Because the API now writes to
`inbox/`, the `vd-api` container mounts `data/videos` (previously only the
worker and watcher did). The web reverse proxy raises `client_max_body_size`
and disables request buffering on `/api/` to pass multi-GB uploads through.

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
    intake_dir: Path = Path("/data/videos/intake")
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
    subclass_retrain_threshold: int = 25
    yolo_base_model: str = "yolo11l.pt"
    insightface_pack: str = "buffalo_l"

    # delete vs retain
    delete_processed_videos: bool = False       # if true, remove from /processed on cleanup
    compress_processed_videos: bool = True      # if true, transcode to HEVC via NVENC after extract
    compress_crf: int = 22                       # NVENC -cq (CRF analog)

    # external job submission (spec 04 §Jobs, spec 05 vd.deliver_callback)
    webhook_timeout_sec: float = 10.0           # per-attempt POST timeout
    webhook_max_attempts: int = 5               # retries before delivery is 'failed'
```

The same `.env` is loaded by both the host-run API and the containerized
worker. The compose file maps it in via `env_file`.

## Env vars (canonical list)

| Var                                | Default                                | Notes                                |
|------------------------------------|----------------------------------------|--------------------------------------|
| `VD_DATABASE_URL`                  | `postgresql+asyncpg://vd:vd@…`         |                                       |
| `VD_REDIS_URL`                     | `redis://localhost:6379/0`             |                                       |
| `VD_INBOX_DIR`                     | `/data/videos/inbox`                   | watched folder                        |
| `VD_INTAKE_DIR`                    | `/data/videos/intake`                  | allowed root for `POST /api/jobs` paths; not watched |
| `VD_FRAMES_DIR`                    | `/data/frames`                         |                                       |
| `VD_MODELS_DIR`                    | `/data/models`                         |                                       |
| `VD_FRAME_FPS`                     | `1.0`                                  | sampling rate                         |
| `VD_DETECTION_MIN_CONFIDENCE`      | `0.25`                                 | "no objects" cutoff                   |
| `VD_SUBCLASS_MIN_CONFIDENCE`       | `0.55`                                 | cosine-sim threshold for kNN          |
| `VD_DETECT_BATCH_SIZE`             | `16`                                   | unused since Phase 9 (was frames per `vd.detect_frame_batch`); reserved |
| `VD_TRACKER`                       | `botsort.yaml`                         | Ultralytics tracker config for `vd.detect_and_track_clip` (built-in name or absolute path) |
| `VD_COMPRESS_PROCESSED_VIDEOS`     | `true`                                 | schedule `vd.compress_video` after extract (spec 05) |
| `VD_COMPRESS_CRF`                  | `22`                                   | NVENC `-cq` target quality            |
| `VD_PRUNE_SIMILAR_FRAMES`          | `true`                                 | enable `vd.dedup_clip_frames` (spec 05) |
| `VD_FRAME_SIMILARITY_THRESHOLD`    | `6`                                    | max pHash Hamming distance for a dup   |
| `VD_WEBHOOK_TIMEOUT_SEC`           | `10.0`                                 | per-attempt callback POST timeout      |
| `VD_WEBHOOK_MAX_ATTEMPTS`          | `5`                                    | callback retries before giving up      |

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

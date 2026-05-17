# CUDA 12.8: the worker GPU is Blackwell (sm_120); 12.4 torch wheels carry no
# kernels for that arch and abort with "no kernel image is available".
FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04 AS base

# Build-only: keep apt non-interactive (tzdata otherwise prompts for a timezone).
ARG DEBIAN_FRONTEND=noninteractive

# Ubuntu 22.04 ships Python 3.10; 3.12 comes from the deadsnakes PPA.
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3.12-venv python3-pip \
    ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

# ──────────────────────────────────────────────────────────
# GPU target — includes torch+cu128, ultralytics, insightface
# ──────────────────────────────────────────────────────────
FROM base AS gpu

COPY apps/worker/pyproject.toml apps/worker/uv.lock /app/apps/worker/
# Only the lib *manifests* — copying full lib source here would invalidate
# the third-party install layer below on every lib edit, forcing a full
# reinstall of torch/ultralytics/insightface.
COPY libs/python/settings/pyproject.toml /app/libs/python/settings/
COPY libs/python/db/pyproject.toml       /app/libs/python/db/
COPY libs/python/tasks/pyproject.toml    /app/libs/python/tasks/
COPY libs/python/ml/pyproject.toml       /app/libs/python/ml/

# insightface 0.7.3 publishes only an sdist whose Cython/C++ extension is
# compiled at install time, so the gpu image needs a C++ toolchain + Python
# headers. Install, build, then purge the compiler in one layer so the
# runtime image doesn't carry it. --no-install-package skips the editable
# local libs (no source present yet); they're linked by the second sync.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential python3.12-dev \
    && cd /app/apps/worker && uv sync --frozen --no-dev --extra gpu \
    --no-install-package vd-settings --no-install-package vd-db \
    --no-install-package vd-tasks --no-install-package vd-ml \
    && apt-get purge -y build-essential python3.12-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY libs/python /app/libs/python
COPY apps/worker /app/apps/worker

# Editable-link the local libs now that their source is present. The heavy
# third-party deps are already installed, so this layer is fast and is the
# only one a lib source edit invalidates.
RUN cd /app/apps/worker && uv sync --frozen --no-dev --extra gpu

# Put the uv-synced venv on PATH so a bare `celery` resolves — the
# docker-compose `command:` overrides CMD and invokes celery directly.
ENV PATH=/app/apps/worker/.venv/bin:$PATH
ENV PYTHONPATH=/app/apps/worker/src
# Persist InsightFace + Hugging Face (DINOv2) weights on the mounted models
# volume so they download once, not on every container start.
ENV INSIGHTFACE_HOME=/data/models/insightface \
    HF_HOME=/data/models/hf
CMD ["celery", "-A", "worker.app", "worker", "-Q", "gpu,train", "-c", "1", "--loglevel=INFO"]

# ──────────────────────────────────────────────────────────
# CPU target — CPU-only torch; for ingest + ffmpeg work
# ──────────────────────────────────────────────────────────
FROM base AS cpu

COPY apps/worker/pyproject.toml apps/worker/uv.lock /app/apps/worker/
# See gpu target: manifests only, so the install layer survives lib edits.
COPY libs/python/settings/pyproject.toml /app/libs/python/settings/
COPY libs/python/db/pyproject.toml       /app/libs/python/db/
COPY libs/python/tasks/pyproject.toml    /app/libs/python/tasks/
COPY libs/python/ml/pyproject.toml       /app/libs/python/ml/

RUN cd /app/apps/worker && uv sync --frozen --no-dev --extra cpu \
    --no-install-package vd-settings --no-install-package vd-db \
    --no-install-package vd-tasks --no-install-package vd-ml

COPY libs/python /app/libs/python
COPY apps/worker /app/apps/worker

RUN cd /app/apps/worker && uv sync --frozen --no-dev --extra cpu

ENV PATH=/app/apps/worker/.venv/bin:$PATH
ENV PYTHONPATH=/app/apps/worker/src
CMD ["celery", "-A", "worker.app", "worker", "-Q", "cpu", "-c", "2", "--loglevel=INFO"]

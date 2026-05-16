FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 AS base

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
# GPU target — includes torch+cu124, ultralytics, insightface
# ──────────────────────────────────────────────────────────
FROM base AS gpu

COPY apps/worker/pyproject.toml apps/worker/uv.lock /app/apps/worker/
COPY libs/python /app/libs/python

# insightface 0.7.3 publishes only an sdist whose Cython/C++ extension is
# compiled at install time, so the gpu image needs a C++ toolchain + Python
# headers. Install, build, then purge the compiler in one layer so the
# runtime image doesn't carry it.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential python3.12-dev \
    && cd /app/apps/worker && uv sync --frozen --no-dev --extra gpu \
    && apt-get purge -y build-essential python3.12-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY apps/worker /app/apps/worker

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
COPY libs/python /app/libs/python

RUN cd /app/apps/worker && uv sync --frozen --no-dev --extra cpu

COPY apps/worker /app/apps/worker

ENV PATH=/app/apps/worker/.venv/bin:$PATH
ENV PYTHONPATH=/app/apps/worker/src
CMD ["celery", "-A", "worker.app", "worker", "-Q", "cpu", "-c", "2", "--loglevel=INFO"]

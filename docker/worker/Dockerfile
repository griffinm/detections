FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3.12-venv python3-pip \
    ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

# ──────────────────────────────────────────────────────────
# GPU target — includes torch+cu124, ultralytics, insightface
# ──────────────────────────────────────────────────────────
FROM base AS gpu

COPY apps/worker/pyproject.toml /app/apps/worker/pyproject.toml
COPY libs/python /app/libs/python

RUN cd /app/apps/worker && uv sync --frozen --no-dev --extra gpu

COPY apps/worker /app/apps/worker

ENV PYTHONPATH=/app/apps/worker/src
# Persist InsightFace + Hugging Face (DINOv2) weights on the mounted models
# volume so they download once, not on every container start.
ENV INSIGHTFACE_HOME=/data/models/insightface \
    HF_HOME=/data/models/hf
CMD ["uv", "run", "celery", "-A", "worker.app", "worker", "-Q", "gpu,train", "-c", "1", "--loglevel=INFO"]

# ──────────────────────────────────────────────────────────
# CPU target — CPU-only torch; for ingest + ffmpeg work
# ──────────────────────────────────────────────────────────
FROM base AS cpu

COPY apps/worker/pyproject.toml /app/apps/worker/pyproject.toml
COPY libs/python /app/libs/python

RUN cd /app/apps/worker && uv sync --frozen --no-dev --extra cpu

COPY apps/worker /app/apps/worker

ENV PYTHONPATH=/app/apps/worker/src
CMD ["uv", "run", "celery", "-A", "worker.app", "worker", "-Q", "cpu", "-c", "2", "--loglevel=INFO"]

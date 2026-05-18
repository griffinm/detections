# FastAPI service. Light image — no torch/CUDA, unlike the worker.
FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

# Manifests only first, so the third-party install layer survives lib edits
# (same rationale as docker/worker/Dockerfile).
COPY apps/api/pyproject.toml apps/api/uv.lock /app/apps/api/
COPY libs/python/settings/pyproject.toml /app/libs/python/settings/
COPY libs/python/db/pyproject.toml       /app/libs/python/db/
COPY libs/python/tasks/pyproject.toml    /app/libs/python/tasks/

RUN cd /app/apps/api && uv sync --frozen --no-dev \
    --no-install-package vd-settings --no-install-package vd-db \
    --no-install-package vd-tasks

COPY libs/python /app/libs/python
COPY apps/api /app/apps/api

RUN cd /app/apps/api && uv sync --frozen --no-dev

ENV PATH=/app/apps/api/.venv/bin:$PATH
ENV PYTHONPATH=/app/apps/api/src

# Apply any pending Alembic migrations, then serve. `alembic` must run from
# the dir holding alembic.ini (script_location is relative); env.py reads the
# DB URL from VD_DATABASE_URL via vd_settings.
CMD ["sh", "-c", "cd /app/libs/python/db && alembic upgrade head && cd /app && exec uvicorn api.main:app --host 0.0.0.0 --port 8000"]

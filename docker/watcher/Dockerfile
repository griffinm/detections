FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY apps/ingest-watcher/pyproject.toml /app/apps/ingest-watcher/pyproject.toml
COPY libs/python /app/libs/python

RUN cd /app/apps/ingest-watcher && uv sync --frozen --no-dev

COPY apps/ingest-watcher /app/apps/ingest-watcher

ENV PYTHONPATH=/app/apps/ingest-watcher/src
CMD ["uv", "run", "python", "-m", "watcher.main"]

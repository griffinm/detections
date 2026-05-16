FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY apps/ingest-watcher/pyproject.toml apps/ingest-watcher/uv.lock /app/apps/ingest-watcher/
COPY libs/python /app/libs/python

RUN cd /app/apps/ingest-watcher && uv sync --frozen --no-dev

COPY apps/ingest-watcher /app/apps/ingest-watcher

ENV PATH=/app/apps/ingest-watcher/.venv/bin:$PATH
ENV PYTHONPATH=/app/apps/ingest-watcher/src
CMD ["python", "-m", "watcher.main"]

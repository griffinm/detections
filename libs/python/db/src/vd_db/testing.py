"""Test-support helpers: provision and reset throwaway Postgres databases.

Framework-agnostic — the pytest fixtures live in each project's `conftest.py`
and call these. Requires a running Postgres (the docker-compose `postgres`
service). Each project uses its own `*_test_<label>` database so test runs
don't collide when nx executes them in parallel.

Schema is built from the ORM metadata (`create_all`), not Alembic: the HNSW
vector indexes are skipped (a query-performance concern, not correctness) but
the builtin classes are seeded exactly as migrations 001 + 002 leave them.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from vd_settings import Settings

from vd_db import models as _models  # noqa: F401 — import populates Base.metadata
from vd_db.base import Base

# (name, yolo_class_index, color_hex) — mirrors migrations 001 + 002.
BUILTIN_CLASSES: Sequence[tuple[str, int, str]] = (
    ("person", 0, "#ef4444"),
    ("car", 2, "#3b82f6"),
    ("dog", 16, "#f59e0b"),
    ("bear", 21, "#8b5cf6"),
)

# Everything except `classes`, which holds the seed.
_MUTABLE_TABLES = (
    "detection_audits", "subclass_examples", "detections", "frames",
    "webhook_deliveries", "clips", "training_runs", "model_versions",
    "subclasses", "settings_kv",
)


def make_test_url(label: str, base_url: str | None = None) -> str:
    """Derive a `<db>_test_<label>` URL from the configured database URL."""
    url = make_url(base_url or Settings().database_url)
    base = (url.database or "video_detection").removesuffix("_test")
    return url.set(database=f"{base}_test_{label}").render_as_string(hide_password=False)


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, poolclass=NullPool)


async def ensure_database(url: str) -> None:
    """Create the target database if it does not already exist."""
    target = make_url(url)
    admin = create_async_engine(
        target.set(database="postgres").render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    try:
        async with admin.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": target.database},
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    finally:
        await admin.dispose()


async def reset_schema(engine: AsyncEngine) -> None:
    """Drop and recreate every table, then seed the builtin classes."""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        for name, index, color in BUILTIN_CLASSES:
            await conn.execute(
                text(
                    "INSERT INTO classes "
                    "(id, name, source, yolo_class_index, color_hex, is_active) "
                    "VALUES (:id, :name, 'builtin', :idx, :color, true)"
                ),
                {"id": uuid.uuid4(), "name": name, "idx": index, "color": color},
            )


async def truncate_mutable(engine: AsyncEngine) -> None:
    """Clear every table except the seeded `classes` — call between tests."""
    async with engine.begin() as conn:
        await conn.execute(
            text(f"TRUNCATE {', '.join(_MUTABLE_TABLES)} RESTART IDENTITY CASCADE")
        )


async def provision(url: str) -> None:
    """Ensure the test database exists and has a fresh schema + seed."""
    await ensure_database(url)
    engine = make_engine(url)
    try:
        await reset_schema(engine)
    finally:
        await engine.dispose()

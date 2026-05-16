"""API test harness.

Runs the FastAPI app in-process via httpx's ASGI transport, with the `get_db`
dependency overridden to a session on a throwaway test database. Needs the
docker-compose `postgres` service running.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.deps import get_db
from api.main import app
from vd_db import testing as dbtest

_TEST_URL = dbtest.make_test_url("api")


@pytest.fixture(scope="session", autouse=True)
def _provision_db() -> None:
    asyncio.run(dbtest.provision(_TEST_URL))


@pytest.fixture
async def engine():  # type: ignore[no-untyped-def]
    eng = dbtest.make_engine(_TEST_URL)
    await dbtest.truncate_mutable(eng)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:  # type: ignore[no-untyped-def]
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub event publishing + task dispatch so tests need no Redis/Celery."""

    async def _noop(*args: object, **kwargs: object) -> None:
        return None

    def _noop_sync(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr("api.routers.detections.publish", _noop)
    monkeypatch.setattr("api.routers.frames.publish", _noop)
    monkeypatch.setattr("api.routers.models.publish", _noop)
    monkeypatch.setattr("api.routers.classes.enqueue", _noop_sync)
    monkeypatch.setattr("api.routers.clips.enqueue", _noop_sync)
    monkeypatch.setattr("api.routers.detections.enqueue", _noop_sync)
    monkeypatch.setattr("api.routers.system.enqueue", _noop_sync)
    monkeypatch.setattr("api.routers.training.enqueue", _noop_sync)
    monkeypatch.setattr("api.services.training_service.enqueue", _noop_sync)


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()

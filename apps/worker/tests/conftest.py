"""Worker test harness.

The worker tasks open their own DB sessions via `Settings()`, so tests can't
inject a session — instead they point `VD_DATABASE_URL` at a throwaway test
database and truncate it between tests. Needs the docker-compose `postgres`
service running.
"""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from vd_db import testing as dbtest

_TEST_URL = dbtest.make_test_url("worker")


@pytest.fixture(scope="session", autouse=True)
def _provision_db() -> None:
    asyncio.run(dbtest.provision(_TEST_URL))


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("VD_DATABASE_URL", _TEST_URL)
    monkeypatch.setenv("VD_FRAMES_DIR", str(tmp_path / "frames"))
    monkeypatch.setenv("VD_MODELS_DIR", str(tmp_path / "models"))


@pytest.fixture
def frames_dir(tmp_path):  # type: ignore[no-untyped-def]
    d = tmp_path / "frames"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
async def engine():  # type: ignore[no-untyped-def]
    eng = dbtest.make_engine(_TEST_URL)
    await dbtest.truncate_mutable(eng)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine):  # type: ignore[no-untyped-def]
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s

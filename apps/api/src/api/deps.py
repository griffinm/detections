from collections.abc import AsyncIterator

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from vd_settings import Settings

settings = Settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def get_redis() -> aioredis.Redis:  # type: ignore[type-arg]
    return aioredis.from_url(settings.redis_url, decode_responses=True)


def enqueue(name: str, *args: object, queue: str) -> None:
    """Send a Celery task. Celery is imported lazily so it stays off the API
    startup path — the API never runs tasks, only dispatches them."""
    from vd_tasks.app import celery_app

    celery_app.send_task(name, args=list(args), queue=queue)

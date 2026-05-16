import json

import redis.asyncio as aioredis

from vd_settings import Settings

_CHANNEL = "vd:events"


async def publish(event_type: str, **kwargs: object) -> None:
    settings = Settings()
    r: aioredis.Redis = aioredis.from_url(settings.redis_url, decode_responses=True)  # type: ignore[type-arg]
    try:
        payload = json.dumps({"type": event_type, **kwargs})
        await r.publish(_CHANNEL, payload)
    finally:
        await r.aclose()

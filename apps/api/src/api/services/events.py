"""Publish events to the Redis pub/sub channel the SSE stream relays.

Mirrors the worker's `worker.events.publish`; the API uses it to notify
listeners when a user edits detections.
"""

import json

from api.deps import get_redis

_CHANNEL = "vd:events"


async def publish(event_type: str, **kwargs: object) -> None:
    redis = get_redis()
    try:
        await redis.publish(_CHANNEL, json.dumps({"type": event_type, **kwargs}))
    finally:
        await redis.aclose()

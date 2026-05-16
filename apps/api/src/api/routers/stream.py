import redis.asyncio as aioredis
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from api.deps import settings

router = APIRouter(prefix="/stream", tags=["stream"])


@router.get("/events")
async def events() -> StreamingResponse:
    async def generator():
        r: aioredis.Redis = aioredis.from_url(settings.redis_url, decode_responses=True)  # type: ignore[type-arg]
        pubsub = r.pubsub()
        await pubsub.subscribe("vd:events")
        try:
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg.get("data"):
                    yield f"data: {msg['data']}\n\n"
                else:
                    yield ": keepalive\n\n"
        finally:
            await pubsub.unsubscribe("vd:events")
            await pubsub.close()
            await r.aclose()

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

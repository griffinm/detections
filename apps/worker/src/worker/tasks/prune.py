import asyncio
import uuid

from vd_db import load_effective_settings
from vd_db.models import Frame
from vd_tasks.app import celery_app

from worker.db import db_session


async def _prune_frame_async(frame_id: str, force: bool) -> bool:
    async with db_session() as session:
        settings = await load_effective_settings(session)
        # The empty-frame caller honours `delete_frames_without_objects`; the
        # dedup caller passes force=True — a near-duplicate frame is redundant
        # by definition, and `prune_similar_frames` was already checked once
        # in vd.dedup_clip_frames.
        if not force and not settings.delete_frames_without_objects:
            return False

        frame = await session.get(Frame, uuid.UUID(frame_id))
        if frame is None or frame.kept or frame.path is None:
            return False
        (settings.frames_dir / frame.path).unlink(missing_ok=True)
        frame.path = None
        await session.commit()
    return True


@celery_app.task(name="vd.prune_frame", bind=True, max_retries=3)
def prune_frame(self, frame_id: str, force: bool = False) -> bool:  # type: ignore[misc]
    try:
        return asyncio.run(_prune_frame_async(frame_id, force))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10) from exc

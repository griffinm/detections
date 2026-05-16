"""`vd.delete_clip` — remove a clip, its frames/detections, and its files.

The row delete cascades frames + detections via the `ondelete=CASCADE` FKs;
the on-disk frame directory is always removed, and the source video only when
`delete_processed_videos` is set. Idempotent: a missing clip is a no-op.
"""

import asyncio
import shutil
import uuid
from pathlib import Path

from sqlalchemy import delete
from vd_db import load_effective_settings
from vd_db.models import Clip
from vd_tasks.app import celery_app

from worker.db import db_session
from worker.events import publish


async def _delete_clip_async(clip_id: str) -> bool:
    cid = uuid.UUID(clip_id)

    async with db_session() as session:
        settings = await load_effective_settings(session)
        clip = await session.get(Clip, cid)
        if clip is None:
            return False
        final_path = clip.final_path
        delete_video = settings.delete_processed_videos
        frames_dir = settings.frames_dir / clip_id
        # Core DELETE so the DB `ondelete=CASCADE` FKs drop frames + detections;
        # an ORM `session.delete` would instead try to NULL the child FKs.
        await session.execute(delete(Clip).where(Clip.id == cid))
        await session.commit()

    # Files come after the row delete so a crash leaves no dangling row.
    shutil.rmtree(frames_dir, ignore_errors=True)
    if delete_video and final_path:
        Path(final_path).unlink(missing_ok=True)

    await publish("clip.deleted", clip_id=clip_id)
    return True


@celery_app.task(name="vd.delete_clip", bind=True, max_retries=3)
def delete_clip(self, clip_id: str) -> bool:  # type: ignore[misc]
    try:
        return asyncio.run(_delete_clip_async(clip_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10) from exc

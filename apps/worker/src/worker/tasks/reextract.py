"""`vd.reextract_frames` — wipe a clip's frames and re-run extraction + detection.

Used by the clip detail page's "Re-extract frames" button. Idempotent: the
DB delete + status reset commit before any file work, so a crash leaves the
clip in `extracting` with no frames — a re-run sees zero frames + zero
detections and proceeds cleanly.

The Frame delete cascades through the FK graph: detections → audits +
subclass_examples. That matches `vd.delete_clip`'s contract — promoting an
example from a detection that you then re-extract loses the example, which
is consistent and what the UI confirmation dialog warns about.
"""

import asyncio
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete
from vd_db import load_effective_settings
from vd_db.models import Clip, Frame, Track
from vd_tasks.app import celery_app

from worker.db import db_session
from worker.events import publish


async def _reextract_frames_async(clip_id: str) -> bool:
    cid = uuid.UUID(clip_id)

    async with db_session() as session:
        settings = await load_effective_settings(session)
        clip = await session.get(Clip, cid)
        if clip is None:
            return False
        if clip.final_path is None or not Path(clip.final_path).exists():
            # The API guards against this too; check again here in case the
            # video disappeared between the click and the task running.
            clip.status = "failed"
            clip.error = "Source video missing — cannot re-extract."
            await session.commit()
            await publish("clip.status", clip_id=clip_id, status="failed")
            return False

        frames_dir = settings.frames_dir / clip_id
        # Drop Frame rows first — CASCADE wipes detections, audits, examples.
        await session.execute(delete(Frame).where(Frame.clip_id == cid))
        # Tracks are per-clip and not FK'd through frames; wipe them too so
        # the re-extract produces a fresh tracker run.
        await session.execute(delete(Track).where(Track.clip_id == cid))
        clip.status = "extracting"
        clip.processed_at = None
        clip.error = None
        clip.ingested_at = datetime.now(UTC)
        await session.commit()

    shutil.rmtree(frames_dir, ignore_errors=True)
    celery_app.send_task("vd.extract_frames", args=[clip_id], queue="cpu")
    await publish("clip.status", clip_id=clip_id, status="extracting")
    return True


@celery_app.task(name="vd.reextract_frames", bind=True, max_retries=3)
def reextract_frames(self, clip_id: str) -> bool:  # type: ignore[misc]
    try:
        return asyncio.run(_reextract_frames_async(clip_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10) from exc

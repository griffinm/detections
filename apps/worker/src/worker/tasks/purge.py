import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from vd_db import load_effective_settings
from vd_db.models import Clip, Frame
from vd_tasks.app import celery_app

from worker.db import db_session


async def _purge_frames_async(older_than_days: int) -> int:
    """Reclaim disk by deleting JPEGs of frames whose clip is older than the
    cutoff. Frame + detection rows are kept (the audit ledger stays intact);
    only `path` is nulled so the UI knows the image is gone."""
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)

    async with db_session() as session:
        settings = await load_effective_settings(session)
        frames = list(
            await session.scalars(
                select(Frame)
                .join(Clip, Clip.id == Frame.clip_id)
                .where(Clip.created_at < cutoff, Frame.path.is_not(None))
            )
        )
        for frame in frames:
            if frame.path is not None:
                (settings.frames_dir / frame.path).unlink(missing_ok=True)
                frame.path = None
        await session.commit()
    return len(frames)


@celery_app.task(name="vd.purge_frames", bind=True, max_retries=3)
def purge_frames(self, older_than_days: int) -> int:  # type: ignore[misc]
    try:
        return asyncio.run(_purge_frames_async(older_than_days))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=30) from exc

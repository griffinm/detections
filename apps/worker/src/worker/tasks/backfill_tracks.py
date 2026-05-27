"""`vd.backfill_tracks` — re-track pre-Phase-9 clips.

Pre-Phase-9 clips have detections but no `tracks` rows. To get them tracked we
re-run `vd.detect_and_track_clip`, but the existing task skips frames whose
`detect_status='done'` — and a pre-Phase-9 clip's frames are all `done`. So we:

1. Delete the clip's unreviewed model-source detections (CASCADE wipes their
   audits). User-source detections and reviewed model detections survive
   with `track_id=NULL` — they're ground truth.
2. Flip the clip's kept frames back to `detect_status='pending'`.
3. Reset clip status to `detecting`.
4. Schedule `vd.detect_and_track_clip(clip_id)`.

Idempotent: a clip that already has any live track is skipped, so re-runs
converge. Targeted (one clip) and sweep (`clip_id=None`) variants — the
sweep walks oldest-first so a `/system` button can chew through the backlog.
"""

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update

from vd_db.models import Clip, DetectionModel, Frame, Track
from vd_tasks.app import celery_app

from worker.db import db_session


async def _eligible_clip_ids(session, limit: int) -> list[uuid.UUID]:  # type: ignore[no-untyped-def]
    """Clips with at least one live detection but no live track."""
    detected = (
        select(Frame.clip_id)
        .join(DetectionModel, DetectionModel.frame_id == Frame.id)
        .where(DetectionModel.deleted_at.is_(None))
        .distinct()
    )
    tracked = (
        select(Track.clip_id).where(Track.deleted_at.is_(None)).distinct()
    )
    rows = await session.scalars(
        select(Clip.id)
        .where(Clip.id.in_(detected), Clip.id.notin_(tracked))
        .order_by(Clip.ingested_at)
        .limit(limit)
    )
    return list(rows)


async def _backfill_one(session, clip_id: uuid.UUID) -> bool:  # type: ignore[no-untyped-def]
    """Reset a single clip so detect_and_track_clip can re-run. Returns False
    if the clip was already tracked (idempotent skip)."""

    already_tracked = await session.scalar(
        select(func.count())
        .select_from(Track)
        .where(Track.clip_id == clip_id, Track.deleted_at.is_(None))
    )
    if already_tracked:
        return False

    frame_ids_subq = select(Frame.id).where(Frame.clip_id == clip_id).subquery()
    await session.execute(
        delete(DetectionModel).where(
            DetectionModel.source == "model",
            DetectionModel.reviewed.is_(False),
            DetectionModel.deleted_at.is_(None),
            DetectionModel.frame_id.in_(select(frame_ids_subq)),
        )
    )
    await session.execute(
        update(Frame)
        .where(Frame.clip_id == clip_id, Frame.kept.is_(True))
        .values(detect_status="pending")
    )
    await session.execute(
        update(Clip)
        .where(Clip.id == clip_id, Clip.status == "done")
        .values(status="detecting", processed_at=None, ingested_at=datetime.now(UTC))
    )
    return True


async def _backfill_tracks_async(clip_id: str | None, limit: int) -> int:
    scheduled = 0

    async with db_session() as session:
        if clip_id is not None:
            targets = [uuid.UUID(clip_id)]
        else:
            targets = await _eligible_clip_ids(session, limit)

        for cid in targets:
            did = await _backfill_one(session, cid)
            if did:
                scheduled += 1
        await session.commit()

    for cid in targets:
        # Schedule outside the DB session — the worker won't process it until
        # this task returns and the row commits are visible.
        celery_app.send_task(
            "vd.detect_and_track_clip", args=[str(cid)], queue="gpu"
        )
    return scheduled


@celery_app.task(name="vd.backfill_tracks", bind=True, max_retries=3)
def backfill_tracks(  # type: ignore[misc]
    self, clip_id: str | None = None, limit: int = 100
) -> int:
    try:
        return asyncio.run(_backfill_tracks_async(clip_id, limit))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10) from exc

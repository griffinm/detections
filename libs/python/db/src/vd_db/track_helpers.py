"""Track aggregate maintenance — shared by worker (dedup, detect+track) and
the API (split/merge/PATCH).

`recount_clip_tracks` recomputes every live track's `n_detections` plus
`first_frame_index` / `last_frame_index` against the current set of live
member detections. Tracks left with zero live members get soft-deleted
(`deleted_at`). Caller is responsible for committing.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import DetectionModel, Frame, Track


async def recount_clip_tracks(session: AsyncSession, clip_id: uuid.UUID) -> None:
    rows = (
        await session.execute(
            select(
                DetectionModel.track_id,
                func.count().label("n"),
                func.min(Frame.frame_index).label("first_idx"),
                func.max(Frame.frame_index).label("last_idx"),
            )
            .join(Frame, Frame.id == DetectionModel.frame_id)
            .where(
                Frame.clip_id == clip_id,
                DetectionModel.track_id.is_not(None),
                DetectionModel.deleted_at.is_(None),
            )
            .group_by(DetectionModel.track_id)
        )
    ).all()
    live: dict[uuid.UUID, tuple[int, int, int]] = {
        tid: (int(n), int(first_idx), int(last_idx))
        for tid, n, first_idx, last_idx in rows
    }
    tracks = list(
        await session.scalars(
            select(Track).where(Track.clip_id == clip_id, Track.deleted_at.is_(None))
        )
    )
    now = datetime.now(UTC)
    for track in tracks:
        stats = live.get(track.id)
        if stats is None:
            track.deleted_at = now
            track.n_detections = 0
            continue
        n, first_idx, last_idx = stats
        track.n_detections = n
        track.first_frame_index = first_idx
        track.last_frame_index = last_idx

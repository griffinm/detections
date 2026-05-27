"""Track-level write path — PATCH, split, merge, delete.

Track actions are equivalent to applying the same change to every live member
detection: PATCHing `subclass_id=Mallory` on a track writes the per-detection
audits as if the user had clicked "Mallory" on each box individually, plus a
single `TrackAudit` row recording the track-level intent. Split / merge are
purely structural (no class/subclass change at the per-detection level) and
only emit `TrackAudit` rows.

`recount_clip_tracks` (in `vd_db`) is the canonical aggregate-maintenance
helper; split/merge call it after re-pointing detections so both halves'
`n_detections` + `first/last_frame_index` stay accurate.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vd_db import recount_clip_tracks
from vd_db.models import (
    DetectionModel,
    Frame,
    Track,
    TrackAudit,
)

from .audits import make_audit


@dataclass
class TrackUpdateResult:
    """What changed when a track-level PATCH ran — used by callers to drive
    SSE invalidation and the auto-trigger training check."""

    track_changed: bool = False
    affected_detection_ids: list[uuid.UUID] = field(default_factory=list)
    affected_frame_ids: set[uuid.UUID] = field(default_factory=set)
    affected_class_ids: set[uuid.UUID | None] = field(default_factory=set)


async def apply_track_update(
    db: AsyncSession,
    track: Track,
    *,
    class_id: uuid.UUID | None = None,
    subclass_id: uuid.UUID | None = None,
    reviewed: bool | None = None,
    fields_set: set[str],
) -> TrackUpdateResult:
    """Apply a track-level PATCH. `fields_set` lists which fields were
    explicitly provided (so `None` can distinguish 'unset' from 'clear')."""

    result = TrackUpdateResult()
    class_change = "class_id" in fields_set and class_id != track.class_id
    subclass_change = "subclass_id" in fields_set and subclass_id != track.subclass_id
    review_change = (
        "reviewed" in fields_set
        and reviewed is not None
        and reviewed != track.reviewed
    )

    if class_change or subclass_change:
        db.add(
            TrackAudit(
                track_id=track.id,
                reason="user_reassign",
                from_class_id=track.class_id,
                to_class_id=class_id if class_change else track.class_id,
                from_subclass_id=track.subclass_id,
                to_subclass_id=subclass_id if subclass_change else track.subclass_id,
                model_version_id=track.model_version_id,
            )
        )
        if class_change:
            track.class_id = class_id
        if subclass_change:
            track.subclass_id = subclass_id
        result.track_changed = True
        if track.class_id is not None:
            result.affected_class_ids.add(track.class_id)

    if review_change:
        db.add(
            TrackAudit(
                track_id=track.id,
                reason="user_review",
                to_class_id=track.class_id,
                to_subclass_id=track.subclass_id,
                model_version_id=track.model_version_id,
            )
        )
        track.reviewed = bool(reviewed)
        track.reviewed_at = datetime.now(UTC) if reviewed else None
        result.track_changed = True

    if not (class_change or subclass_change or review_change):
        return result

    # Propagate to live members. Match what a user clicking each detection
    # individually would produce so existing accuracy queries don't have to
    # special-case track-driven writes.
    members = list(
        await db.scalars(
            select(DetectionModel).where(
                DetectionModel.track_id == track.id,
                DetectionModel.deleted_at.is_(None),
            )
        )
    )
    for det in members:
        det_class_change = class_change and det.class_id != track.class_id
        det_subclass_change = subclass_change and det.subclass_id != track.subclass_id
        if det_class_change or det_subclass_change:
            db.add(
                make_audit(
                    det,
                    reason="user_reassign",
                    from_class_id=det.class_id,
                    to_class_id=track.class_id if det_class_change else det.class_id,
                    from_subclass_id=det.subclass_id,
                    to_subclass_id=track.subclass_id
                    if det_subclass_change
                    else det.subclass_id,
                )
            )
            if det_class_change:
                det.class_id = track.class_id
            if det_subclass_change:
                det.subclass_id = track.subclass_id
            result.affected_detection_ids.append(det.id)
            result.affected_frame_ids.add(det.frame_id)

        if review_change and reviewed and not det.reviewed:
            det.reviewed = True
            det.reviewed_at = datetime.now(UTC)
            db.add(
                make_audit(det, reason="user_review", to_class_id=det.class_id)
            )
            result.affected_detection_ids.append(det.id)
            result.affected_frame_ids.add(det.frame_id)
        elif review_change and reviewed is False and det.reviewed:
            det.reviewed = False
            det.reviewed_at = None
            result.affected_detection_ids.append(det.id)
            result.affected_frame_ids.add(det.frame_id)

    return result


async def split_track(
    db: AsyncSession, track: Track, pivot_frame_index: int
) -> Track:
    """Carve detections with `frame_index >= pivot` off into a new track.

    Validates that the pivot leaves both halves with ≥1 detection. Raises
    ValueError on a degenerate split — the router maps that to 422.
    """
    if pivot_frame_index <= track.first_frame_index:
        raise ValueError(
            f"pivot_frame_index {pivot_frame_index} must be > track first frame "
            f"{track.first_frame_index}"
        )
    if pivot_frame_index > track.last_frame_index:
        raise ValueError(
            f"pivot_frame_index {pivot_frame_index} must be ≤ track last frame "
            f"{track.last_frame_index}"
        )

    new_track = Track(
        clip_id=track.clip_id,
        class_id=track.class_id,
        subclass_id=track.subclass_id,
        predicted_class_id=track.predicted_class_id,
        predicted_subclass_id=track.predicted_subclass_id,
        confidence_class=track.confidence_class,
        confidence_subclass=track.confidence_subclass,
        source="user",
        model_version_id=track.model_version_id,
        first_frame_index=pivot_frame_index,
        last_frame_index=track.last_frame_index,
        n_detections=0,
    )
    db.add(new_track)
    await db.flush()

    # Re-point detections whose frame_index >= pivot. Single UPDATE through a
    # subquery — avoids loading the rows.
    moved_frame_ids = list(
        await db.scalars(
            select(Frame.id).where(
                Frame.clip_id == track.clip_id,
                Frame.frame_index >= pivot_frame_index,
            )
        )
    )
    result = await db.execute(
        update(DetectionModel)
        .where(
            DetectionModel.track_id == track.id,
            DetectionModel.frame_id.in_(moved_frame_ids),
        )
        .values(track_id=new_track.id)
    )
    moved = int(result.rowcount or 0)

    await recount_clip_tracks(db, track.clip_id)

    db.add(
        TrackAudit(
            track_id=new_track.id,
            reason="user_split",
            from_track_id=track.id,
            to_track_id=new_track.id,
            pivot_frame_index=pivot_frame_index,
            n_detections_moved=moved,
            model_version_id=track.model_version_id,
        )
    )
    return new_track


async def merge_tracks(db: AsyncSession, target: Track, other: Track) -> int:
    """Absorb `other` into `target`. Returns the number of detections moved."""

    if target.clip_id != other.clip_id:
        raise ValueError("Tracks must belong to the same clip")
    if target.class_id != other.class_id:
        raise ValueError("Tracks must share the same class_id to be merged")
    overlaps = (
        target.first_frame_index <= other.last_frame_index
        and other.first_frame_index <= target.last_frame_index
    )
    if overlaps:
        raise ValueError(
            "Track frame ranges overlap — one object can't be in two places "
            "at once. Use split first, or delete the redundant track."
        )

    result = await db.execute(
        update(DetectionModel)
        .where(DetectionModel.track_id == other.id)
        .values(track_id=target.id)
    )
    moved = int(result.rowcount or 0)

    other.deleted_at = datetime.now(UTC)
    other.n_detections = 0

    await recount_clip_tracks(db, target.clip_id)

    db.add(
        TrackAudit(
            track_id=target.id,
            reason="user_merge",
            from_track_id=other.id,
            to_track_id=target.id,
            n_detections_moved=moved,
            model_version_id=target.model_version_id,
        )
    )
    return moved


async def soft_delete_track(db: AsyncSession, track: Track) -> set[uuid.UUID]:
    """Soft-delete a track and every live member detection. Returns affected
    frame ids so the caller can broadcast SSE invalidations."""

    members = list(
        await db.scalars(
            select(DetectionModel).where(
                DetectionModel.track_id == track.id,
                DetectionModel.deleted_at.is_(None),
            )
        )
    )
    now = datetime.now(UTC)
    affected_frames: set[uuid.UUID] = set()
    for det in members:
        det.deleted_at = now
        db.add(make_audit(det, reason="user_delete", from_class_id=det.class_id))
        affected_frames.add(det.frame_id)

    track.deleted_at = now
    track.n_detections = 0
    db.add(
        TrackAudit(
            track_id=track.id,
            reason="user_delete",
            from_class_id=track.class_id,
            from_subclass_id=track.subclass_id,
            model_version_id=track.model_version_id,
        )
    )
    return affected_frames

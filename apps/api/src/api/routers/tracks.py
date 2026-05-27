"""`/api/tracks/*` — track-level read + edit endpoints.

Track actions delegate to `services.tracks_service`, which writes both the
track-level `TrackAudit` row and the per-detection `DetectionAudit` rows so
classification accuracy queries don't need to special-case track-driven
changes. Split/merge are pure structural edits and emit only `TrackAudit`.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas.detection import Bbox
from api.schemas.tracks import (
    TrackDetail,
    TrackMember,
    TrackMerge,
    TrackRead,
    TrackSplit,
    TrackUpdate,
    TrackUpdateResponse,
)
from api.services.events import publish
from api.services.tracks_service import (
    apply_track_update,
    merge_tracks,
    soft_delete_track,
    split_track,
)
from api.services.training_service import maybe_trigger_training
from vd_db.models import DetectionModel, Frame, Track

router = APIRouter(prefix="/tracks", tags=["tracks"])


# A separate clip-scoped GET lives in routers.clips; see list_clip_tracks below
# which is mounted via `clips_router.include_router` for `/api/clips/{id}/tracks`.
# Keeping the prefix-grouped router for everything keyed on a `track_id`.


async def _load_track(db: AsyncSession, track_id: uuid.UUID) -> Track:
    track = await db.get(Track, track_id)
    if track is None or track.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Track not found")
    return track


async def _track_members(db: AsyncSession, track_id: uuid.UUID) -> list[TrackMember]:
    rows = (
        await db.execute(
            select(DetectionModel, Frame.frame_index)
            .join(Frame, Frame.id == DetectionModel.frame_id)
            .where(
                DetectionModel.track_id == track_id,
                DetectionModel.deleted_at.is_(None),
            )
            .order_by(Frame.frame_index)
        )
    ).all()
    return [
        TrackMember(
            id=det.id,
            frame_id=det.frame_id,
            frame_index=int(frame_index),
            bbox=Bbox(**det.bbox),
            class_id=det.class_id,
            subclass_id=det.subclass_id,
            confidence_class=det.confidence_class,
            confidence_subclass=det.confidence_subclass,
            source=det.source,
            reviewed=det.reviewed,
        )
        for det, frame_index in rows
    ]


@router.get("/{track_id}", response_model=TrackDetail)
async def get_track(
    track_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> TrackDetail:
    track = await _load_track(db, track_id)
    members = await _track_members(db, track_id)
    return TrackDetail(track=TrackRead.model_validate(track), members=members)


@router.patch("/{track_id}", response_model=TrackUpdateResponse)
async def update_track(
    track_id: uuid.UUID,
    payload: TrackUpdate,
    db: AsyncSession = Depends(get_db),
) -> TrackUpdateResponse:
    track = await _load_track(db, track_id)
    fields_set = set(payload.model_fields_set)

    result = await apply_track_update(
        db,
        track,
        class_id=payload.class_id,
        subclass_id=payload.subclass_id,
        reviewed=payload.reviewed,
        fields_set=fields_set,
    )
    await db.commit()
    await db.refresh(track)

    for frame_id in result.affected_frame_ids:
        clip_id = await db.scalar(select(Frame.clip_id).where(Frame.id == frame_id))
        if clip_id is not None:
            await publish(
                "frame.updated", clip_id=str(clip_id), frame_id=str(frame_id)
            )
    if result.track_changed:
        await publish(
            "track.updated", clip_id=str(track.clip_id), track_id=str(track.id)
        )
    if result.affected_class_ids:
        await maybe_trigger_training(db, result.affected_class_ids)

    # audits_written = track-level events (≤2) + per-detection rows
    audits = (1 if result.track_changed else 0) + len(result.affected_detection_ids)
    return TrackUpdateResponse(
        track=TrackRead.model_validate(track),
        updated_detections=len(result.affected_detection_ids),
        audits_written=audits,
        affected_frame_ids=sorted(result.affected_frame_ids),
    )


@router.post("/{track_id}/split", response_model=TrackDetail)
async def split_track_endpoint(
    track_id: uuid.UUID,
    payload: TrackSplit,
    db: AsyncSession = Depends(get_db),
) -> TrackDetail:
    track = await _load_track(db, track_id)
    try:
        new_track = await split_track(db, track, payload.pivot_frame_index)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await db.commit()
    await db.refresh(new_track)
    await publish(
        "track.split",
        clip_id=str(track.clip_id),
        track_id=str(track.id),
        new_track_id=str(new_track.id),
    )
    members = await _track_members(db, new_track.id)
    return TrackDetail(track=TrackRead.model_validate(new_track), members=members)


@router.post("/{track_id}/merge", response_model=TrackDetail)
async def merge_track_endpoint(
    track_id: uuid.UUID,
    payload: TrackMerge,
    db: AsyncSession = Depends(get_db),
) -> TrackDetail:
    target = await _load_track(db, track_id)
    other = await _load_track(db, payload.other_track_id)
    if target.id == other.id:
        raise HTTPException(status_code=422, detail="Cannot merge a track with itself")

    try:
        await merge_tracks(db, target, other)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await db.commit()
    await db.refresh(target)
    await publish(
        "track.merged",
        clip_id=str(target.clip_id),
        track_id=str(target.id),
        absorbed_track_id=str(other.id),
    )
    members = await _track_members(db, target.id)
    return TrackDetail(track=TrackRead.model_validate(target), members=members)


@router.delete("/{track_id}", status_code=204)
async def delete_track(
    track_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    track = await _load_track(db, track_id)
    affected_frames = await soft_delete_track(db, track)
    await db.commit()

    for frame_id in affected_frames:
        clip_id = await db.scalar(select(Frame.clip_id).where(Frame.id == frame_id))
        if clip_id is not None:
            await publish(
                "frame.updated", clip_id=str(clip_id), frame_id=str(frame_id)
            )
    await publish(
        "track.deleted", clip_id=str(track.clip_id), track_id=str(track.id)
    )

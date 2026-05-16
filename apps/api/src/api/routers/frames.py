import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas.detection import DetectionRead
from api.schemas.frame import FrameDetail, FrameRead
from api.services.events import publish
from api.services.training_service import maybe_trigger_training
from vd_db.models import DetectionAudit, DetectionModel, Frame

router = APIRouter(prefix="/frames", tags=["frames"])


async def _active_detections(
    db: AsyncSession, frame_id: uuid.UUID
) -> Sequence[DetectionModel]:
    """Detections on a frame that haven't been soft-deleted, in stable order."""
    rows = await db.scalars(
        select(DetectionModel)
        .where(
            DetectionModel.frame_id == frame_id,
            DetectionModel.deleted_at.is_(None),
        )
        .order_by(DetectionModel.created_at)
    )
    return rows.all()


def _frame_detail(frame: Frame, detections: Sequence[DetectionModel]) -> FrameDetail:
    base = FrameRead.model_validate(frame).model_dump()
    base["image_url"] = f"/files/frames/{frame.path}" if frame.path else None
    return FrameDetail(
        **base,
        detections=[DetectionRead.model_validate(d) for d in detections],
    )


@router.get("/{frame_id}", response_model=FrameDetail)
async def get_frame(
    frame_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> FrameDetail:
    frame = await db.get(Frame, frame_id)
    if frame is None:
        raise HTTPException(status_code=404, detail="Frame not found")
    return _frame_detail(frame, await _active_detections(db, frame_id))


@router.post("/{frame_id}/review", response_model=FrameDetail)
async def review_frame(
    frame_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> FrameDetail:
    """Mark every unreviewed detection on the frame as reviewed (the "Save")."""
    frame = await db.get(Frame, frame_id)
    if frame is None:
        raise HTTPException(status_code=404, detail="Frame not found")

    unreviewed = list(
        await db.scalars(
            select(DetectionModel).where(
                DetectionModel.frame_id == frame_id,
                DetectionModel.deleted_at.is_(None),
                ~DetectionModel.reviewed,
            )
        )
    )
    now = datetime.now(UTC)
    for det in unreviewed:
        det.reviewed = True
        det.reviewed_at = now
        db.add(
            DetectionAudit(
                detection_id=det.id,
                reason="user_review",
                to_class_id=det.class_id,
                model_version_id=det.model_version_id,
            )
        )
    await db.commit()
    await publish("frame.updated", clip_id=str(frame.clip_id), frame_id=str(frame.id))
    await maybe_trigger_training(db, {det.class_id for det in unreviewed})
    return _frame_detail(frame, await _active_detections(db, frame_id))

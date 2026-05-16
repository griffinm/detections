"""The review queue — frames that still have unreviewed detections."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas.labeling import LabelingQueueItem
from vd_db.models import Clip, DetectionModel, Frame

router = APIRouter(prefix="/labeling", tags=["labeling"])

_STRATEGIES = {"lowconf", "unreviewed"}


@router.get("/queue", response_model=list[LabelingQueueItem])
async def get_queue(
    strategy: str = Query(default="lowconf"),
    class_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> list[LabelingQueueItem]:
    if strategy not in _STRATEGIES:
        raise HTTPException(status_code=400, detail=f"Unsupported strategy: {strategy}")

    unreviewed = func.count().filter(~DetectionModel.reviewed)
    min_conf = func.min(DetectionModel.confidence_class).filter(~DetectionModel.reviewed)

    query = (
        select(
            Frame.id,
            Frame.clip_id,
            Frame.frame_index,
            Frame.path,
            Clip.filename,
            unreviewed.label("unreviewed"),
            min_conf.label("min_conf"),
        )
        .join(DetectionModel, DetectionModel.frame_id == Frame.id)
        .join(Clip, Clip.id == Frame.clip_id)
        .where(DetectionModel.deleted_at.is_(None), Frame.kept.is_(True))
        .group_by(Frame.id, Frame.clip_id, Frame.frame_index, Frame.path, Clip.filename)
        .having(unreviewed > 0)
    )
    if class_id is not None:
        # Class-targeted: the aggregates + the having-count cover only this
        # class, so frames with no unreviewed detection of it drop out.
        query = query.where(DetectionModel.class_id == class_id)

    if strategy == "lowconf":
        query = query.order_by(min_conf.asc().nulls_last())
    else:  # unreviewed — newest unfinished frames first
        query = query.order_by(Frame.created_at.desc())

    rows = (await db.execute(query.limit(limit))).all()
    return [
        LabelingQueueItem(
            frame_id=row.id,
            clip_id=row.clip_id,
            clip_filename=row.filename,
            frame_index=row.frame_index,
            image_url=f"/files/frames/{row.path}" if row.path else None,
            unreviewed_count=row.unreviewed,
            min_confidence=row.min_conf,
        )
        for row in rows
    ]

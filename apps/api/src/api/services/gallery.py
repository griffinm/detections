"""Shared query for the class / sub-class detection gallery.

Used by both `/api/subclasses/{id}/detections` and
`/api/classes/{id}/detections`. The variable bit is the WHERE clause; the
join + sort + soft-delete filter + result projection are identical.
"""

from typing import Literal

from sqlalchemy import ColumnElement, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.detection import Bbox, DetectionGalleryItem
from api.services.crops import crop_url
from vd_db.models import DetectionModel, Frame

GalleryInclude = Literal["all", "auto", "reviewed"]
GallerySort = Literal["created_desc", "reviewed_desc"]


async def query_gallery_items(
    db: AsyncSession,
    *,
    where: ColumnElement[bool],
    include: GalleryInclude,
    sort: GallerySort,
    limit: int,
) -> list[DetectionGalleryItem]:
    query = (
        select(DetectionModel, Frame.path, Frame.clip_id)
        .join(Frame, Frame.id == DetectionModel.frame_id)
        .where(where)
        .where(DetectionModel.deleted_at.is_(None))
    )

    if include == "auto":
        query = query.where(DetectionModel.reviewed.is_(False))
    elif include == "reviewed":
        query = query.where(DetectionModel.reviewed.is_(True))

    if sort == "reviewed_desc":
        query = query.order_by(
            desc(DetectionModel.reviewed_at).nulls_last(),
            desc(DetectionModel.created_at),
        )
    else:
        query = query.order_by(desc(DetectionModel.created_at))

    rows = (await db.execute(query.limit(limit))).all()
    return [
        DetectionGalleryItem(
            id=det.id,
            frame_id=det.frame_id,
            clip_id=clip_id,
            class_id=det.class_id,
            subclass_id=det.subclass_id,
            bbox=Bbox(**det.bbox),
            image_url=f"/files/frames/{frame_path}" if frame_path else None,
            crop_url=crop_url(str(det.id)) if frame_path else None,
            source=det.source,
            reviewed=det.reviewed,
            reviewed_at=det.reviewed_at,
            created_at=det.created_at,
        )
        for det, frame_path, clip_id in rows
    ]

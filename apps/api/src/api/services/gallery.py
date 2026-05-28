"""Shared query for the class / sub-class / clip detection gallery.

Used by the class, sub-class, and clip detection endpoints. The variable bit
is the WHERE clause and the sort key; the join + soft-delete filter + result
projection are identical.
"""

from typing import Literal

from sqlalchemy import ColumnElement, asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.common import Paginated
from api.schemas.detection import Bbox, DetectionGalleryItem
from api.services.crops import crop_url
from api.utils.pagination import offset_page
from vd_db.models import DetectionModel, Frame

GalleryInclude = Literal["all", "auto", "reviewed"]
GallerySort = Literal["created_desc", "reviewed_desc", "frame_asc"]


def _gallery_query(
    *,
    where: ColumnElement[bool],
    include: GalleryInclude,
    sort: GallerySort,
):
    query = (
        select(DetectionModel, Frame.path, Frame.clip_id, Frame.frame_index)
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
    elif sort == "frame_asc":
        # Clip view: read the clip left-to-right by frame, then stable on
        # creation order so multiple detections per frame have a fixed order.
        query = query.order_by(asc(Frame.frame_index), asc(DetectionModel.created_at))
    else:
        query = query.order_by(desc(DetectionModel.created_at))
    return query


def _gallery_item(det: DetectionModel, frame_path: str | None, clip_id) -> DetectionGalleryItem:
    return DetectionGalleryItem(
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


async def query_gallery_items(
    db: AsyncSession,
    *,
    where: ColumnElement[bool],
    include: GalleryInclude,
    sort: GallerySort,
    limit: int,
) -> list[DetectionGalleryItem]:
    """Flat list of gallery items, no pagination envelope.

    Used by endpoints that intentionally return everything (clip tile grids,
    labeling drill-downs) where the dataset is bounded by an upstream filter.
    Paginated endpoints should use `query_gallery_page` instead.
    """
    query = _gallery_query(where=where, include=include, sort=sort).limit(limit)
    rows = (await db.execute(query)).all()
    return [_gallery_item(det, path, clip_id) for det, path, clip_id, _ in rows]


async def query_gallery_page(
    db: AsyncSession,
    *,
    where: ColumnElement[bool],
    include: GalleryInclude,
    sort: GallerySort,
    offset: int,
    limit: int,
) -> Paginated[DetectionGalleryItem]:
    """Offset-paginated gallery slice. Returns a `Paginated` envelope.

    Offset (not keyset) because `reviewed_desc` sorts by `reviewed_at NULLS
    LAST, created_at` — a composite a single `(sort_col, id)` cursor can't
    express without losing the NULL semantics the UI relies on.
    """
    count_query = (
        select(func.count(DetectionModel.id))
        .join(Frame, Frame.id == DetectionModel.frame_id)
        .where(where)
        .where(DetectionModel.deleted_at.is_(None))
    )
    if include == "auto":
        count_query = count_query.where(DetectionModel.reviewed.is_(False))
    elif include == "reviewed":
        count_query = count_query.where(DetectionModel.reviewed.is_(True))
    total = await db.scalar(count_query) or 0

    query = _gallery_query(where=where, include=include, sort=sort)
    rows = (await db.execute(query.offset(offset).limit(limit))).all()
    items = [_gallery_item(det, path, clip_id) for det, path, clip_id, _ in rows]
    return offset_page(items, offset=offset, limit=limit, total=total)

"""Sub-class management — CRUD plus the examples gallery.

A sub-class is soft-deleted (`is_active=false`) so historical detections that
point at it keep their FK. `subclass_examples` is the user-curated kNN
reference set the worker's `vd.assign_subclass` queries.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas.class_ import (
    SubclassExampleCreate,
    SubclassExampleRead,
    SubclassRead,
    SubclassUpdate,
)
from api.schemas.detection import Bbox, DetectionGalleryItem
from api.services.crops import crop_url
from api.services.gallery import (
    GalleryInclude,
    GallerySort,
    query_gallery_items,
)
from vd_db.models import DetectionModel, Frame, Subclass, SubclassExample

router = APIRouter(prefix="/subclasses", tags=["subclasses"])


def _example_read(
    example: SubclassExample, bbox: dict[str, float], frame: Frame
) -> SubclassExampleRead:
    return SubclassExampleRead(
        id=example.id,
        subclass_id=example.subclass_id,
        detection_id=example.detection_id,
        starred=example.starred,
        created_at=example.created_at,
        bbox=Bbox(**bbox),
        frame_id=frame.id,
        image_url=f"/files/frames/{frame.path}" if frame.path else None,
        crop_url=crop_url(str(example.detection_id)) if frame.path else None,
    )


@router.get("", response_model=list[SubclassRead])
async def list_subclasses(
    class_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[Subclass]:
    query = select(Subclass).order_by(Subclass.name)
    if class_id is not None:
        query = query.where(Subclass.class_id == class_id)
    return list(await db.scalars(query))


@router.get("/{subclass_id}", response_model=SubclassRead)
async def get_subclass(
    subclass_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Subclass:
    subclass = await db.get(Subclass, subclass_id)
    if subclass is None:
        raise HTTPException(status_code=404, detail="Sub-class not found")
    return subclass


@router.patch("/{subclass_id}", response_model=SubclassRead)
async def update_subclass(
    subclass_id: uuid.UUID,
    payload: SubclassUpdate,
    db: AsyncSession = Depends(get_db),
) -> Subclass:
    subclass = await db.get(Subclass, subclass_id)
    if subclass is None:
        raise HTTPException(status_code=404, detail="Sub-class not found")

    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] != subclass.name:
        clash = await db.scalar(
            select(Subclass).where(
                Subclass.class_id == subclass.class_id,
                Subclass.name == data["name"],
                Subclass.id != subclass_id,
            )
        )
        if clash:
            raise HTTPException(status_code=409, detail="Sub-class name already exists")
        subclass.name = data["name"]
    if "color_hex" in data:
        subclass.color_hex = data["color_hex"]
    if "is_active" in data:
        subclass.is_active = data["is_active"]

    await db.commit()
    await db.refresh(subclass)
    return subclass


@router.delete("/{subclass_id}", status_code=204)
async def delete_subclass(
    subclass_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft delete — sub-classes are deactivated, never removed (audit trail)."""
    subclass = await db.get(Subclass, subclass_id)
    if subclass is None:
        raise HTTPException(status_code=404, detail="Sub-class not found")
    subclass.is_active = False
    await db.commit()


@router.get("/{subclass_id}/examples", response_model=list[SubclassExampleRead])
async def list_examples(
    subclass_id: uuid.UUID,
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> list[SubclassExampleRead]:
    subclass = await db.get(Subclass, subclass_id)
    if subclass is None:
        raise HTTPException(status_code=404, detail="Sub-class not found")

    rows = (
        await db.execute(
            select(SubclassExample, DetectionModel.bbox, Frame)
            .join(DetectionModel, DetectionModel.id == SubclassExample.detection_id)
            .join(Frame, Frame.id == DetectionModel.frame_id)
            .where(SubclassExample.subclass_id == subclass_id)
            .order_by(SubclassExample.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [_example_read(example, bbox, frame) for example, bbox, frame in rows]


@router.get("/{subclass_id}/detections", response_model=list[DetectionGalleryItem])
async def list_subclass_detections(
    subclass_id: uuid.UUID,
    include: GalleryInclude = Query(default="all"),
    sort: GallerySort = Query(default="created_desc"),
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> list[DetectionGalleryItem]:
    """Every detection tagged with this sub-class (auto + reviewed), newest first."""
    subclass = await db.get(Subclass, subclass_id)
    if subclass is None:
        raise HTTPException(status_code=404, detail="Sub-class not found")
    return await query_gallery_items(
        db,
        where=DetectionModel.subclass_id == subclass_id,
        include=include,
        sort=sort,
        limit=limit,
    )


@router.post("/{subclass_id}/examples", response_model=SubclassExampleRead, status_code=201)
async def add_example(
    subclass_id: uuid.UUID,
    payload: SubclassExampleCreate,
    db: AsyncSession = Depends(get_db),
) -> SubclassExampleRead:
    subclass = await db.get(Subclass, subclass_id)
    if subclass is None:
        raise HTTPException(status_code=404, detail="Sub-class not found")
    detection = await db.get(DetectionModel, payload.detection_id)
    if detection is None or detection.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Detection not found")
    if await db.scalar(
        select(SubclassExample).where(
            SubclassExample.subclass_id == subclass_id,
            SubclassExample.detection_id == payload.detection_id,
        )
    ):
        raise HTTPException(status_code=409, detail="Detection is already an example")

    example = SubclassExample(subclass_id=subclass_id, detection_id=payload.detection_id)
    db.add(example)
    await db.commit()
    await db.refresh(example)
    frame = await db.get(Frame, detection.frame_id)
    assert frame is not None
    return _example_read(example, detection.bbox, frame)


@router.delete("/{subclass_id}/examples/{example_id}", status_code=204)
async def delete_example(
    subclass_id: uuid.UUID,
    example_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    example = await db.get(SubclassExample, example_id)
    if example is None or example.subclass_id != subclass_id:
        raise HTTPException(status_code=404, detail="Example not found")
    await db.delete(example)
    await db.commit()

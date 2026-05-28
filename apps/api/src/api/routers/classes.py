import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.coco import COCO_80_NAMES
from api.deps import enqueue, get_db
from api.schemas.class_ import (
    ClassCatalogEntry,
    ClassCreate,
    ClassRead,
    ClassUpdate,
    SubclassCreate,
    SubclassExampleRead,
    SubclassRead,
)
from api.schemas.common import Paginated
from api.schemas.detection import Bbox, DetectionGalleryItem
from api.services.crops import crop_url
from api.services.gallery import (
    GalleryInclude,
    GallerySort,
    query_gallery_page,
)
from api.utils.pagination import (
    CursorPage,
    cursor_params,
    offset_from_cursor,
    offset_page,
)
from vd_db.models import (
    Class,
    DetectionModel,
    Frame,
    ModelVersion,
    Subclass,
    SubclassExample,
)

router = APIRouter(prefix="/classes", tags=["classes"])


@router.get("", response_model=list[ClassRead])
async def list_classes(db: AsyncSession = Depends(get_db)) -> list[Class]:
    rows = await db.scalars(select(Class).order_by(Class.name))
    return list(rows)


@router.get("/catalog", response_model=list[ClassCatalogEntry])
async def list_class_catalog(
    db: AsyncSession = Depends(get_db),
) -> list[ClassCatalogEntry]:
    """Names offered to the picker: COCO-80 ∪ active YOLO model's class list.

    The active model's `ModelVersion.metrics["class_names"]` (the same dict
    consulted by `_sync_yolo_class_index`) supplies the indices the model
    actually emits — including any custom classes a fine-tune introduced.
    COCO-80 fills in the baseline names that every off-the-shelf YOLO knows
    about, even when a fine-tune has trimmed the active model down to a
    handful of classes. For names only present in COCO-80 (not in the active
    model), `yolo_class_index` is null: storing the COCO index would
    disagree with whatever the active fine-tune emits at that slot, and
    `_sync_yolo_class_index` will fill the right value if/when a model that
    knows the name is activated.
    """
    active = await db.scalar(
        select(ModelVersion).where(
            ModelVersion.kind == "yolo",
            ModelVersion.target_class_id.is_(None),
            ModelVersion.is_active.is_(True),
        )
    )
    active_class_names: dict[str, str] = (
        (active.metrics or {}).get("class_names", {}) if active else {}
    )
    active_index_by_name: dict[str, int] = {
        name: int(idx) for idx, name in active_class_names.items()
    }

    taken_names = set((await db.scalars(select(Class.name))).all())

    # Union of COCO-80 baseline and the active model's names. Active model's
    # index wins where both know the name; COCO-only names get a null index.
    names: set[str] = set(COCO_80_NAMES.values()) | set(active_index_by_name)
    entries = [
        ClassCatalogEntry(
            name=name,
            yolo_class_index=active_index_by_name.get(name),
            in_use=name in taken_names,
        )
        for name in names
    ]
    entries.sort(key=lambda e: e.name)
    return entries


@router.post("", response_model=ClassRead, status_code=201)
async def create_class(
    payload: ClassCreate,
    db: AsyncSession = Depends(get_db),
) -> Class:
    if await db.scalar(select(Class).where(Class.name == payload.name)):
        raise HTTPException(status_code=409, detail="Class name already exists")
    if payload.yolo_class_index is not None and await db.scalar(
        select(Class).where(Class.yolo_class_index == payload.yolo_class_index)
    ):
        raise HTTPException(
            status_code=409,
            detail="Another class already owns that YOLO class index",
        )
    cls = Class(
        name=payload.name,
        color_hex=payload.color_hex,
        source="custom",
        is_active=True,
        yolo_class_index=payload.yolo_class_index,
    )
    db.add(cls)
    await db.commit()
    await db.refresh(cls)
    return cls


@router.patch("/{class_id}", response_model=ClassRead)
async def update_class(
    class_id: uuid.UUID,
    payload: ClassUpdate,
    db: AsyncSession = Depends(get_db),
) -> Class:
    cls = await db.get(Class, class_id)
    if cls is None:
        raise HTTPException(status_code=404, detail="Class not found")

    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] != cls.name:
        clash = await db.scalar(
            select(Class).where(Class.name == data["name"], Class.id != class_id)
        )
        if clash:
            raise HTTPException(status_code=409, detail="Class name already exists")
        cls.name = data["name"]
    if "color_hex" in data:
        cls.color_hex = data["color_hex"]
    if "is_active" in data:
        cls.is_active = data["is_active"]

    await db.commit()
    await db.refresh(cls)
    return cls


@router.delete("/{class_id}", status_code=204)
async def delete_class(
    class_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft delete — classes are deactivated, never removed (audit trail)."""
    cls = await db.get(Class, class_id)
    if cls is None:
        raise HTTPException(status_code=404, detail="Class not found")
    cls.is_active = False
    await db.commit()


@router.get("/{class_id}/subclasses", response_model=list[SubclassRead])
async def list_class_subclasses(
    class_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[Subclass]:
    cls = await db.get(Class, class_id)
    if cls is None:
        raise HTTPException(status_code=404, detail="Class not found")
    rows = await db.scalars(
        select(Subclass).where(Subclass.class_id == class_id).order_by(Subclass.name)
    )
    return list(rows)


@router.post("/{class_id}/subclasses", response_model=SubclassRead, status_code=201)
async def create_subclass(
    class_id: uuid.UUID,
    payload: SubclassCreate,
    db: AsyncSession = Depends(get_db),
) -> Subclass:
    cls = await db.get(Class, class_id)
    if cls is None:
        raise HTTPException(status_code=404, detail="Class not found")
    if await db.scalar(
        select(Subclass).where(
            Subclass.class_id == class_id, Subclass.name == payload.name
        )
    ):
        raise HTTPException(status_code=409, detail="Sub-class name already exists")

    # The first active sub-class makes the class eligible for kNN — backfill
    # embeddings + assignment for detections from already-ingested clips.
    had_active = await db.scalar(
        select(Subclass.id)
        .where(Subclass.class_id == class_id, Subclass.is_active.is_(True))
        .limit(1)
    )
    subclass = Subclass(
        class_id=class_id,
        name=payload.name,
        color_hex=payload.color_hex,
        is_active=True,
    )
    db.add(subclass)
    await db.commit()
    await db.refresh(subclass)
    if had_active is None:
        enqueue("vd.backfill_embeddings", str(class_id), queue="gpu")
    return subclass


@router.get("/{class_id}/detections", response_model=Paginated[DetectionGalleryItem])
async def list_class_detections(
    class_id: uuid.UUID,
    include: GalleryInclude = Query(default="all"),
    sort: GallerySort = Query(default="created_desc"),
    page: CursorPage = Depends(cursor_params),
    db: AsyncSession = Depends(get_db),
) -> Paginated[DetectionGalleryItem]:
    """Every non-deleted detection tagged with this class (any sub-class or none)."""
    cls = await db.get(Class, class_id)
    if cls is None:
        raise HTTPException(status_code=404, detail="Class not found")
    return await query_gallery_page(
        db,
        where=DetectionModel.class_id == class_id,
        include=include,
        sort=sort,
        offset=offset_from_cursor(page.cursor),
        limit=page.limit,
    )


@router.get("/{class_id}/examples", response_model=Paginated[SubclassExampleRead])
async def list_class_examples(
    class_id: uuid.UUID,
    page: CursorPage = Depends(cursor_params),
    db: AsyncSession = Depends(get_db),
) -> Paginated[SubclassExampleRead]:
    """Curated examples across every active sub-class of this class."""
    cls = await db.get(Class, class_id)
    if cls is None:
        raise HTTPException(status_code=404, detail="Class not found")
    base = (
        select(SubclassExample.id)
        .join(Subclass, Subclass.id == SubclassExample.subclass_id)
        .join(DetectionModel, DetectionModel.id == SubclassExample.detection_id)
        .where(
            Subclass.class_id == class_id,
            Subclass.is_active.is_(True),
            DetectionModel.deleted_at.is_(None),
        )
    )
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    offset = offset_from_cursor(page.cursor)
    rows = (
        await db.execute(
            select(SubclassExample, DetectionModel.bbox, Frame)
            .join(Subclass, Subclass.id == SubclassExample.subclass_id)
            .join(DetectionModel, DetectionModel.id == SubclassExample.detection_id)
            .join(Frame, Frame.id == DetectionModel.frame_id)
            .where(
                Subclass.class_id == class_id,
                Subclass.is_active.is_(True),
                DetectionModel.deleted_at.is_(None),
            )
            .order_by(SubclassExample.created_at.desc(), SubclassExample.id.desc())
            .offset(offset)
            .limit(page.limit)
        )
    ).all()
    items = [
        SubclassExampleRead(
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
        for example, bbox, frame in rows
    ]
    return offset_page(items, offset=offset, limit=page.limit, total=total)


@router.post("/{class_id}/rescan-subclasses", status_code=202)
async def rescan_subclasses(
    class_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Re-run embedding + kNN assignment over every detection of this class."""
    cls = await db.get(Class, class_id)
    if cls is None:
        raise HTTPException(status_code=404, detail="Class not found")
    enqueue("vd.backfill_embeddings", str(class_id), queue="gpu")
    return {"status": "queued"}

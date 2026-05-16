import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import enqueue, get_db
from api.schemas.class_ import (
    ClassCreate,
    ClassRead,
    ClassUpdate,
    SubclassCreate,
    SubclassRead,
)
from vd_db.models import Class, Subclass

router = APIRouter(prefix="/classes", tags=["classes"])


@router.get("", response_model=list[ClassRead])
async def list_classes(db: AsyncSession = Depends(get_db)) -> list[Class]:
    rows = await db.scalars(select(Class).order_by(Class.name))
    return list(rows)


@router.post("", response_model=ClassRead, status_code=201)
async def create_class(
    payload: ClassCreate,
    db: AsyncSession = Depends(get_db),
) -> Class:
    if await db.scalar(select(Class).where(Class.name == payload.name)):
        raise HTTPException(status_code=409, detail="Class name already exists")
    cls = Class(
        name=payload.name,
        color_hex=payload.color_hex,
        source="custom",
        is_active=True,
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

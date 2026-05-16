"""Model registry — list every `model_versions` row and activate one.

Activation goes through `vd_db.activate_model_version` (shared with the worker)
so the "one active per (kind, target_class_id)" invariant and the YOLO
class-index sync are enforced identically wherever a model is activated.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas.model import ModelVersionRead
from api.services.events import publish
from vd_db import activate_model_version
from vd_db.models import ModelVersion

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[ModelVersionRead])
async def list_models(
    kind: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[ModelVersion]:
    query = select(ModelVersion).order_by(ModelVersion.created_at.desc())
    if kind is not None:
        query = query.where(ModelVersion.kind == kind)
    return list(await db.scalars(query))


@router.post("/{model_id}/activate", response_model=ModelVersionRead)
async def activate_model(
    model_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ModelVersion:
    version = await db.get(ModelVersion, model_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Model version not found")

    await activate_model_version(db, version)
    await db.commit()
    await db.refresh(version)

    payload: dict[str, str] = {"kind": version.kind, "model_version_id": str(version.id)}
    if version.target_class_id is not None:
        payload["target_class_id"] = str(version.target_class_id)
    await publish("model.active_changed", **payload)
    return version

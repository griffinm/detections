"""Model registry — list every `model_versions` row and activate one.

Activation goes through `vd_db.activate_model_version` (shared with the worker)
so the "one active per (kind, target_class_id)" invariant and the YOLO
class-index sync are enforced identically wherever a model is activated.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas.common import Paginated
from api.schemas.model import ModelVersionRead
from api.services.events import publish
from api.utils.pagination import CursorPage, apply_keyset, build_page, cursor_params
from vd_db import activate_model_version
from vd_db.models import ModelVersion

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=Paginated[ModelVersionRead])
async def list_models(
    kind: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    page: CursorPage = Depends(cursor_params),
    db: AsyncSession = Depends(get_db),
) -> Paginated[ModelVersionRead]:
    base = select(ModelVersion)
    if kind is not None:
        base = base.where(ModelVersion.kind == kind)
    if is_active is not None:
        base = base.where(ModelVersion.is_active.is_(is_active))

    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0

    query = apply_keyset(
        base, ModelVersion.created_at, ModelVersion.id, page.cursor, direction="desc"
    ).limit(page.limit + 1)
    rows = list(await db.scalars(query))

    return build_page(
        rows,
        sort_attr="created_at",
        id_attr="id",
        limit=page.limit,
        total=total,
        item_cls=ModelVersionRead,
    )


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

"""Training runs — create (which dispatches a Celery task) + list + detail.

The API only writes the `training_runs` row and enqueues the task on the
`train` queue; the worker does the actual training (plan 05).
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import enqueue, get_db
from api.schemas.training import TrainingRunCreate, TrainingRunDetail, TrainingRunRead
from vd_db.models import TrainingRun

router = APIRouter(prefix="/training-runs", tags=["training"])

_TASK_BY_KIND = {
    "yolo": "vd.finetune_yolo",
    "classifier": "vd.train_subclass_classifier",
}


def _log_tail(path: str | None, lines: int = 200) -> str | None:
    if not path:
        return None
    file = Path(path)
    if not file.exists():
        return None
    try:
        return "\n".join(file.read_text().splitlines()[-lines:])
    except OSError:
        return None


@router.post("", response_model=TrainingRunRead, status_code=201)
async def create_training_run(
    payload: TrainingRunCreate,
    db: AsyncSession = Depends(get_db),
) -> TrainingRun:
    task = _TASK_BY_KIND.get(payload.kind)
    if task is None:
        raise HTTPException(
            status_code=422, detail=f"Unsupported training kind: {payload.kind}"
        )
    if payload.kind == "classifier" and payload.target_class_id is None:
        raise HTTPException(
            status_code=422, detail="classifier runs require a target_class_id"
        )

    run = TrainingRun(
        kind=payload.kind, target_class_id=payload.target_class_id, status="queued"
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    enqueue(task, str(run.id), queue="train")
    return run


@router.get("", response_model=list[TrainingRunRead])
async def list_training_runs(
    status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[TrainingRun]:
    query = select(TrainingRun).order_by(TrainingRun.created_at.desc())
    if status is not None:
        query = query.where(TrainingRun.status == status)
    if kind is not None:
        query = query.where(TrainingRun.kind == kind)
    return list(await db.scalars(query))


@router.get("/{run_id}", response_model=TrainingRunDetail)
async def get_training_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> TrainingRunDetail:
    run = await db.get(TrainingRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Training run not found")
    base = TrainingRunRead.model_validate(run).model_dump()
    return TrainingRunDetail(**base, log_tail=_log_tail(run.log_path))

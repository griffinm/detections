"""Training runs — create (which dispatches a Celery task) + list + detail.

The API only writes the `training_runs` row and enqueues the task on the
`train` queue; the worker does the actual training (spec 05).
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import enqueue, get_db
from api.schemas.common import Paginated
from api.schemas.training import (
    TrainingRunCounts,
    TrainingRunCreate,
    TrainingRunDetail,
    TrainingRunRead,
)
from api.services.events import publish
from api.utils.pagination import CursorPage, apply_keyset, build_page, cursor_params
from vd_db.models import TrainingRun

router = APIRouter(prefix="/training-runs", tags=["training"])

_TASK_BY_KIND = {
    "yolo": "vd.finetune_yolo",
    "classifier": "vd.train_subclass_classifier",
}

# Status → bucket mapping. Mirrors `statusBucket()` in apps/web/src/routes/training.tsx.
# The /counts endpoint and the list endpoint's `status` filter both speak buckets,
# not raw enum values — keep the two ends in sync. Enum values come from the
# `run_status` Postgres type: ('queued','running','succeeded','failed','cancelled').
_STATUS_BUCKETS: dict[str, tuple[str, ...]] = {
    "running": ("running",),
    "done": ("succeeded",),
    "failed": ("failed",),
    "queued": ("queued", "cancelled"),
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


def _status_clause(status: str | None):
    """Translate a status bucket (or raw enum) into a SQL clause."""
    if status is None:
        return None
    bucket = _STATUS_BUCKETS.get(status)
    if bucket is not None:
        return TrainingRun.status.in_(bucket)
    return TrainingRun.status == status


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


@router.get("", response_model=Paginated[TrainingRunRead])
async def list_training_runs(
    status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    page: CursorPage = Depends(cursor_params),
    db: AsyncSession = Depends(get_db),
) -> Paginated[TrainingRunRead]:
    base = select(TrainingRun)
    status_clause = _status_clause(status)
    if status_clause is not None:
        base = base.where(status_clause)
    if kind is not None:
        base = base.where(TrainingRun.kind == kind)

    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0

    query = apply_keyset(
        base, TrainingRun.created_at, TrainingRun.id, page.cursor, direction="desc"
    ).limit(page.limit + 1)
    rows = list(await db.scalars(query))

    return build_page(
        rows,
        sort_attr="created_at",
        id_attr="id",
        limit=page.limit,
        total=total,
        item_cls=TrainingRunRead,
    )


# Declared before `/{run_id}` so the literal path wins the route match.
@router.get("/counts", response_model=TrainingRunCounts)
async def get_training_run_counts(
    kind: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> TrainingRunCounts:
    """Faceted bucket counts for the stat strip. Respects `kind`, ignores `status`."""
    base = select(func.count()).select_from(TrainingRun)
    if kind is not None:
        base = base.where(TrainingRun.kind == kind)

    counts: dict[str, int] = {"all": await db.scalar(base) or 0}
    for bucket, statuses in _STATUS_BUCKETS.items():
        counts[bucket] = (
            await db.scalar(base.where(TrainingRun.status.in_(statuses))) or 0
        )
    return TrainingRunCounts(**counts)


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


@router.post("/{run_id}/cancel", response_model=TrainingRunRead)
async def cancel_training_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> TrainingRun:
    # Best-effort: flips the DB row. A genuinely-running task won't observe
    # this mid-training (it only checks status at start) and may still overwrite
    # the row on completion — that's fine; the endpoint exists to clear runs
    # already orphaned by a worker crash.
    run = await db.get(TrainingRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Training run not found")
    if run.status not in ("queued", "running"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel a run with status {run.status!r}",
        )
    run.status = "cancelled"
    run.finished_at = datetime.now(UTC)
    if not run.error:
        run.error = "cancelled by user"
    await db.commit()
    await db.refresh(run)
    await publish("training_run.update", training_run_id=str(run.id), status="cancelled")
    return run

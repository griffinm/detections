"""Auto-trigger sub-class classifier training once enough new labels accumulate.

Called best-effort from the review / detection write endpoints. A per-class
sub-class classifier fires when a class gains `subclass_retrain_threshold`
new sub-class labels.

YOLO fine-tunes are manual-only: kick them off from `/training` (or
`POST /api/training-runs` with `kind="yolo"`).
"""

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import enqueue
from vd_db import load_effective_settings
from vd_db.models import DetectionModel, ModelVersion, TrainingRun

logger = logging.getLogger(__name__)


async def maybe_trigger_classifier(db: AsyncSession, class_id: uuid.UUID) -> None:
    """Enqueue a sub-class classifier retrain when a class gains enough new labels."""
    threshold = (await load_effective_settings(db)).subclass_retrain_threshold

    if await db.scalar(
        select(TrainingRun.id)
        .where(
            TrainingRun.kind == "classifier",
            TrainingRun.target_class_id == class_id,
            TrainingRun.status.in_(("queued", "running")),
        )
        .limit(1)
    ):
        return

    labeled_filter = (
        DetectionModel.class_id == class_id,
        DetectionModel.deleted_at.is_(None),
        DetectionModel.subclass_id.is_not(None),
        DetectionModel.reviewed.is_(True),
    )
    labeled = (
        await db.scalar(
            select(func.count()).select_from(DetectionModel).where(*labeled_filter)
        )
    ) or 0
    distinct_subclasses = (
        await db.scalar(
            select(func.count(func.distinct(DetectionModel.subclass_id))).where(
                *labeled_filter
            )
        )
    ) or 0
    if distinct_subclasses < 2:
        return  # a classifier needs at least two sub-classes

    active = await db.scalar(
        select(ModelVersion).where(
            ModelVersion.kind == "classifier",
            ModelVersion.target_class_id == class_id,
            ModelVersion.is_active.is_(True),
        )
    )
    baseline = (active.trained_on or 0) if active is not None else 0
    if labeled - baseline < threshold:
        return

    run = TrainingRun(kind="classifier", target_class_id=class_id, status="queued")
    db.add(run)
    await db.commit()
    await db.refresh(run)
    enqueue("vd.train_subclass_classifier", str(run.id), queue="train")


async def maybe_trigger_training(
    db: AsyncSession, class_ids: set[uuid.UUID | None]
) -> None:
    """Best-effort: never let an auto-trigger failure break the originating request.

    The originating endpoint has already committed by the time this runs, and
    each trigger commits its own `TrainingRun` independently — so a failure
    here is logged and swallowed, never rolled back (a rollback would only
    discard unrelated session state without undoing the committed request).
    """
    try:
        for class_id in class_ids:
            if class_id is not None:
                await maybe_trigger_classifier(db, class_id)
    except Exception:
        logger.exception("auto-trigger training check failed")

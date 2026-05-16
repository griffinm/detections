"""Auto-trigger training runs once enough new labels accumulate.

Called best-effort from the review / detection write endpoints. A YOLO
fine-tune fires when the labeled dataset grows past
`custom_class_finetune_threshold`; a per-class sub-class classifier fires when a
class gains `subclass_retrain_threshold` new sub-class labels.
"""

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import enqueue
from vd_db import load_effective_settings
from vd_db.models import Class, DetectionModel, ModelVersion, TrainingRun

logger = logging.getLogger(__name__)


def _ground_truth() -> tuple[Any, ...]:
    """Filter for detections that count as training labels (ground truth)."""
    return (
        DetectionModel.deleted_at.is_(None),
        DetectionModel.class_id.is_not(None),
        (DetectionModel.source == "user") | DetectionModel.reviewed.is_(True),
    )


async def maybe_trigger_finetune(db: AsyncSession) -> None:
    """Enqueue a YOLO fine-tune when the labeled dataset has grown past threshold."""
    threshold = (await load_effective_settings(db)).custom_class_finetune_threshold

    if await db.scalar(
        select(TrainingRun.id)
        .where(TrainingRun.kind == "yolo", TrainingRun.status.in_(("queued", "running")))
        .limit(1)
    ):
        return  # a run is already in flight

    last_yolo = await db.scalar(
        select(ModelVersion)
        .where(ModelVersion.kind == "yolo")
        .order_by(ModelVersion.created_at.desc())
        .limit(1)
    )
    is_finetune = (
        last_yolo is not None and (last_yolo.metrics or {}).get("source") == "finetune"
    )
    total = (
        await db.scalar(
            select(func.count()).select_from(DetectionModel).where(*_ground_truth())
        )
    ) or 0

    if is_finetune:
        assert last_yolo is not None
        trigger = total - (last_yolo.trained_on or 0) >= threshold
    else:
        # First fine-tune: only worth it once a custom class has enough labels.
        custom = await db.execute(
            select(func.count())
            .select_from(DetectionModel)
            .join(Class, Class.id == DetectionModel.class_id)
            .where(*_ground_truth(), Class.source == "custom")
            .group_by(DetectionModel.class_id)
        )
        trigger = any(count >= threshold for (count,) in custom)

    if not trigger:
        return

    run = TrainingRun(kind="yolo", status="queued")
    db.add(run)
    await db.commit()
    await db.refresh(run)
    enqueue("vd.finetune_yolo", str(run.id), queue="train")


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
        await maybe_trigger_finetune(db)
        for class_id in class_ids:
            if class_id is not None:
                await maybe_trigger_classifier(db, class_id)
    except Exception:
        logger.exception("auto-trigger training check failed")

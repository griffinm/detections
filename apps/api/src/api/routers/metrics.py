"""Accuracy & observability metrics, computed on-the-fly from the ledger.

Every number derives from `detections` (the current snapshot) and
`detection_audits` (the insert-only ledger). Accuracy is measured only over
reviewed *model* detections — until a user reviews, the truth is unknown.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from api.deps import get_db
from api.schemas.metrics import (
    AccuracyPoint,
    CalibrationBin,
    CalibrationResponse,
    ClassMetric,
    MetricsSummary,
    ReassignmentItem,
)
from vd_db.models import Class, Clip, DetectionAudit, DetectionModel, Frame, Subclass

router = APIRouter(prefix="/metrics", tags=["metrics"])


def _reviewed_model_filter() -> tuple[Any, ...]:
    """Detections that count toward accuracy: reviewed, live, model-produced."""
    return (
        DetectionModel.source == "model",
        DetectionModel.reviewed.is_(True),
        DetectionModel.deleted_at.is_(None),
        DetectionModel.reviewed_at.is_not(None),
    )


def _class_correct() -> Any:
    return case((DetectionModel.predicted_class_id == DetectionModel.class_id, 1.0), else_=0.0)


@router.get("/accuracy", response_model=list[AccuracyPoint])
async def accuracy(
    bucket: str = Query(default="day"),
    class_id: uuid.UUID | None = Query(default=None),
    model_version_id: uuid.UUID | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[AccuracyPoint]:
    if bucket not in ("day", "week"):
        raise HTTPException(status_code=422, detail="bucket must be 'day' or 'week'")

    period = func.date_trunc(bucket, DetectionModel.reviewed_at).label("period")
    subclass_correct = case(
        (
            DetectionModel.predicted_subclass_id.is_not_distinct_from(
                DetectionModel.subclass_id
            ),
            1.0,
        ),
        else_=0.0,
    )
    query = (
        select(
            period,
            DetectionModel.model_version_id,
            func.count().label("n"),
            func.avg(_class_correct()).label("class_top1"),
            func.avg(subclass_correct).label("subclass_top1"),
            func.avg(DetectionModel.confidence_class).label("mean_conf"),
        )
        .where(*_reviewed_model_filter())
        .group_by(period, DetectionModel.model_version_id)
        .order_by(period)
    )
    if class_id is not None:
        query = query.where(DetectionModel.class_id == class_id)
    if model_version_id is not None:
        query = query.where(DetectionModel.model_version_id == model_version_id)
    if from_ is not None:
        query = query.where(DetectionModel.reviewed_at >= from_)
    if to is not None:
        query = query.where(DetectionModel.reviewed_at <= to)

    rows = (await db.execute(query)).all()
    return [
        AccuracyPoint(
            period=row.period,
            model_version_id=row.model_version_id,
            n_reviewed=row.n,
            class_top1=float(row.class_top1 or 0.0),
            subclass_top1=None if row.subclass_top1 is None else float(row.subclass_top1),
            mean_confidence=None if row.mean_conf is None else float(row.mean_conf),
        )
        for row in rows
    ]


@router.get("/per-class", response_model=list[ClassMetric])
async def per_class(
    model_version_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[ClassMetric]:
    base = list(_reviewed_model_filter())
    if model_version_id is not None:
        base.append(DetectionModel.model_version_id == model_version_id)
    correct = _class_correct()

    # Precision: of detections predicted class C, the fraction actually C.
    precision_rows = (
        await db.execute(
            select(
                DetectionModel.predicted_class_id,
                func.count().label("n"),
                func.avg(correct).label("score"),
            )
            .where(*base, DetectionModel.predicted_class_id.is_not(None))
            .group_by(DetectionModel.predicted_class_id)
        )
    ).all()
    # Recall: of detections actually class C, the fraction predicted C.
    recall_rows = (
        await db.execute(
            select(
                DetectionModel.class_id,
                func.count().label("n"),
                func.avg(correct).label("score"),
            )
            .where(*base, DetectionModel.class_id.is_not(None))
            .group_by(DetectionModel.class_id)
        )
    ).all()

    precision = {r[0]: (r.n, float(r.score)) for r in precision_rows}
    recall = {r[0]: (r.n, float(r.score)) for r in recall_rows}
    class_ids = set(precision) | set(recall)
    names = {
        c.id: c.name
        for c in await db.scalars(select(Class).where(Class.id.in_(class_ids)))
    }
    return sorted(
        (
            ClassMetric(
                class_id=cid,
                class_name=names.get(cid, "?"),
                n_predicted=precision.get(cid, (0, None))[0],
                n_actual=recall.get(cid, (0, None))[0],
                precision=precision[cid][1] if cid in precision else None,
                recall=recall[cid][1] if cid in recall else None,
            )
            for cid in class_ids
        ),
        key=lambda m: m.class_name,
    )


@router.get("/calibration", response_model=CalibrationResponse)
async def calibration(
    class_id: uuid.UUID | None = Query(default=None),
    model_version_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> CalibrationResponse:
    bucket = func.width_bucket(DetectionModel.confidence_class, 0.0, 1.0, 10).label("bucket")
    query = (
        select(
            bucket,
            func.count().label("n"),
            func.avg(DetectionModel.confidence_class).label("conf"),
            func.avg(_class_correct()).label("acc"),
        )
        .where(*_reviewed_model_filter(), DetectionModel.confidence_class.is_not(None))
        .group_by(bucket)
        .order_by(bucket)
    )
    if class_id is not None:
        query = query.where(DetectionModel.class_id == class_id)
    if model_version_id is not None:
        query = query.where(DetectionModel.model_version_id == model_version_id)

    rows = (await db.execute(query)).all()
    bins = [
        CalibrationBin(
            bucket=row.bucket,
            mean_confidence=float(row.conf),
            empirical_accuracy=float(row.acc),
            count=row.n,
        )
        for row in rows
    ]
    total = sum(b.count for b in bins)
    ece = (
        sum(abs(b.empirical_accuracy - b.mean_confidence) * b.count for b in bins) / total
        if total
        else 0.0
    )
    return CalibrationResponse(bins=bins, ece=ece)


@router.get("/summary", response_model=MetricsSummary)
async def summary(db: AsyncSession = Depends(get_db)) -> MetricsSummary:
    live = (DetectionModel.deleted_at.is_(None),)
    clips = await db.scalar(select(func.count()).select_from(Clip))
    detections = await db.scalar(
        select(func.count()).select_from(DetectionModel).where(*live)
    )
    reviewed = await db.scalar(
        select(func.count())
        .select_from(DetectionModel)
        .where(*live, DetectionModel.reviewed.is_(True))
    )
    pending = await db.scalar(
        select(func.count())
        .select_from(DetectionModel)
        .where(*live, DetectionModel.reviewed.is_(False))
    )
    last7d = await db.scalar(
        select(func.avg(_class_correct())).where(
            *_reviewed_model_filter(),
            DetectionModel.reviewed_at >= datetime.now(UTC) - timedelta(days=7),
        )
    )
    return MetricsSummary(
        clips=clips or 0,
        detections=detections or 0,
        reviewed=reviewed or 0,
        pending_review=pending or 0,
        last7d_class_accuracy=None if last7d is None else float(last7d),
    )


@router.get("/changes", response_model=list[ReassignmentItem])
async def changes(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[ReassignmentItem]:
    from_class = aliased(Class)
    to_class = aliased(Class)
    from_subclass = aliased(Subclass)
    to_subclass = aliased(Subclass)
    rows = (
        await db.execute(
            select(
                DetectionAudit.detection_id,
                DetectionModel.frame_id,
                Frame.clip_id,
                DetectionAudit.at,
                DetectionAudit.reason,
                from_class.name,
                to_class.name,
                from_subclass.name,
                to_subclass.name,
            )
            .join(DetectionModel, DetectionModel.id == DetectionAudit.detection_id)
            .join(Frame, Frame.id == DetectionModel.frame_id, isouter=True)
            .join(from_class, from_class.id == DetectionAudit.from_class_id, isouter=True)
            .join(to_class, to_class.id == DetectionAudit.to_class_id, isouter=True)
            .join(
                from_subclass,
                from_subclass.id == DetectionAudit.from_subclass_id,
                isouter=True,
            )
            .join(to_subclass, to_subclass.id == DetectionAudit.to_subclass_id, isouter=True)
            .where(DetectionAudit.reason.in_(("user_reassign", "retrain_reassign")))
            .order_by(DetectionAudit.at.desc())
            .limit(limit)
        )
    ).all()
    return [
        ReassignmentItem(
            detection_id=row[0],
            frame_id=row[1],
            clip_id=row[2],
            at=row[3],
            reason=row[4],
            from_class=row[5],
            to_class=row[6],
            from_subclass=row[7],
            to_subclass=row[8],
        )
        for row in rows
    ]

"""The review queue, plus bulk-labeling shortcuts.

`GET /labeling/queue` is the per-frame backlog. `GET /labeling/predicted-groups`
buckets auto-assigned detections by `(class, predicted_subclass, confidence)`
so the user can confirm the model's kNN result for many crops at once.
`POST /labeling/bulk-review` is the shared write path — it applies one set of
field changes to many detections in a single transaction, inferring the audit
reason per row exactly like the per-detection PATCH.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas.detection import Bbox, DetectionGalleryItem
from api.schemas.labeling import (
    BulkReviewRequest,
    BulkReviewResponse,
    ConfidenceBucket,
    EmbeddingKind,
    LabelingQueueItem,
    PredictedGroup,
    SimilarityCluster,
    SimilarityClustersResponse,
)
from api.services.audits import make_audit
from api.services.crops import crop_url
from api.services.events import publish
from api.services.gallery import query_gallery_items
from api.services.training_service import maybe_trigger_training
from vd_db import load_effective_settings
from vd_db.models import Class, Clip, DetectionModel, Frame, Subclass

router = APIRouter(prefix="/labeling", tags=["labeling"])

_STRATEGIES = {"lowconf", "unreviewed"}

# Bucket cutoffs for the predicted-groups view. The model never sets
# `predicted_subclass_id` below `subclass_min_confidence` (kNN gate in
# `vd.assign_subclass`), so the "low" bucket is bounded from below by that.
_BUCKET_HIGH = 0.85
_BUCKET_MED = 0.70

_SAMPLE_LIMIT = 9


@router.get("/queue", response_model=list[LabelingQueueItem])
async def get_queue(
    strategy: str = Query(default="lowconf"),
    class_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> list[LabelingQueueItem]:
    if strategy not in _STRATEGIES:
        raise HTTPException(status_code=400, detail=f"Unsupported strategy: {strategy}")

    unreviewed = func.count().filter(~DetectionModel.reviewed)
    min_conf = func.min(DetectionModel.confidence_class).filter(~DetectionModel.reviewed)

    query = (
        select(
            Frame.id,
            Frame.clip_id,
            Frame.frame_index,
            Frame.path,
            Clip.filename,
            Clip.created_at,
            unreviewed.label("unreviewed"),
            min_conf.label("min_conf"),
        )
        .join(DetectionModel, DetectionModel.frame_id == Frame.id)
        .join(Clip, Clip.id == Frame.clip_id)
        .where(DetectionModel.deleted_at.is_(None), Frame.kept.is_(True))
        .group_by(
            Frame.id,
            Frame.clip_id,
            Frame.frame_index,
            Frame.path,
            Clip.filename,
            Clip.created_at,
        )
        .having(unreviewed > 0)
    )
    if class_id is not None:
        # Class-targeted: the aggregates + the having-count cover only this
        # class, so frames with no unreviewed detection of it drop out.
        query = query.where(DetectionModel.class_id == class_id)

    if strategy == "lowconf":
        query = query.order_by(min_conf.asc().nulls_last())
    else:  # unreviewed — newest unfinished frames first
        query = query.order_by(Frame.created_at.desc())

    rows = (await db.execute(query.limit(limit))).all()
    return [
        LabelingQueueItem(
            frame_id=row.id,
            clip_id=row.clip_id,
            clip_filename=row.filename,
            clip_created_at=row.created_at,
            frame_index=row.frame_index,
            image_url=f"/files/frames/{row.path}" if row.path else None,
            unreviewed_count=row.unreviewed,
            min_confidence=row.min_conf,
        )
        for row in rows
    ]


@router.get("/predicted-groups", response_model=list[PredictedGroup])
async def get_predicted_groups(
    class_id: uuid.UUID | None = Query(default=None),
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
) -> list[PredictedGroup]:
    """Group still-unreviewed detections by their model-assigned sub-class.

    A row appears here only when `vd.assign_subclass` made a prediction the
    user hasn't acted on yet. Default `min_confidence` follows the global
    `subclass_min_confidence` setting — the same gate the worker uses — so
    the surface matches what the kNN actually committed.
    """
    if min_confidence is None:
        min_confidence = (await load_effective_settings(db)).subclass_min_confidence

    bucket = case(
        (DetectionModel.confidence_subclass >= _BUCKET_HIGH, "high"),
        (DetectionModel.confidence_subclass >= _BUCKET_MED, "med"),
        else_="low",
    ).label("bucket")

    bucket_rank = case(
        (DetectionModel.confidence_subclass >= _BUCKET_HIGH, 2),
        (DetectionModel.confidence_subclass >= _BUCKET_MED, 1),
        else_=0,
    )

    query = (
        select(
            DetectionModel.class_id,
            Class.name.label("class_name"),
            DetectionModel.predicted_subclass_id,
            Subclass.name.label("subclass_name"),
            bucket,
            func.count().label("n"),
            func.max(bucket_rank).label("rank"),
            func.array_agg(
                DetectionModel.id,
            ).label("ids"),
        )
        .select_from(DetectionModel)
        .join(Frame, Frame.id == DetectionModel.frame_id)
        .join(Subclass, Subclass.id == DetectionModel.predicted_subclass_id)
        .outerjoin(Class, Class.id == DetectionModel.class_id)
        .where(
            DetectionModel.reviewed.is_(False),
            DetectionModel.deleted_at.is_(None),
            Frame.kept.is_(True),
            DetectionModel.predicted_subclass_id.is_not(None),
            DetectionModel.confidence_subclass >= min_confidence,
        )
        .group_by(
            DetectionModel.class_id,
            Class.name,
            DetectionModel.predicted_subclass_id,
            Subclass.name,
            bucket,
        )
        .order_by(func.max(bucket_rank).desc(), func.count().desc())
    )
    if class_id is not None:
        query = query.where(DetectionModel.class_id == class_id)

    rows = (await db.execute(query)).all()
    return [
        PredictedGroup(
            class_id=row.class_id,
            class_name=row.class_name,
            predicted_subclass_id=row.predicted_subclass_id,
            predicted_subclass_name=row.subclass_name,
            confidence_bucket=row.bucket,
            count=row.n,
            sample_detection_ids=list(row.ids)[:_SAMPLE_LIMIT],
        )
        for row in rows
    ]


@router.get("/predicted-group-detections", response_model=list[DetectionGalleryItem])
async def get_predicted_group_detections(
    predicted_subclass_id: uuid.UUID,
    bucket: ConfidenceBucket | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
) -> list[DetectionGalleryItem]:
    """Full detection list for one (predicted_subclass, bucket) cell.

    `GET /labeling/predicted-groups` is the bucketed index; this is the
    drill-down the bulk-confirm UI renders as a tile grid.
    """
    where = DetectionModel.predicted_subclass_id == predicted_subclass_id
    if bucket == "high":
        where = where & (DetectionModel.confidence_subclass >= _BUCKET_HIGH)
    elif bucket == "med":
        where = (
            where
            & (DetectionModel.confidence_subclass >= _BUCKET_MED)
            & (DetectionModel.confidence_subclass < _BUCKET_HIGH)
        )
    elif bucket == "low":
        where = where & (DetectionModel.confidence_subclass < _BUCKET_MED)

    return await query_gallery_items(
        db, where=where, include="auto", sort="created_desc", limit=limit
    )


@router.get("/similarity-clusters", response_model=SimilarityClustersResponse)
async def get_similarity_clusters(
    class_id: uuid.UUID = Query(...),
    cluster_size: int = Query(default=8, ge=2, le=32),
    max_clusters: int = Query(default=40, ge=1, le=200),
    max_pool: int = Query(default=2000, ge=10, le=10000),
    db: AsyncSession = Depends(get_db),
) -> SimilarityClustersResponse:
    """Group un-reviewed, un-assigned detections of one class by embedding kNN.

    Companion to `predicted-groups`: that view groups by the model's
    `predicted_subclass_id`; this one ignores predictions entirely and
    clusters purely on embedding similarity, so it works even when the
    auto-assigner has nothing to say (no examples yet, low confidence, no
    sub-classes seeded). Greedy seed-iteration: take the oldest un-clustered
    detection as a seed, grab its `cluster_size - 1` nearest neighbors from
    the remaining pool via pgvector HNSW (`ix_detections_*_embedding`), emit
    one cluster, repeat. No precomputed cluster table — the pool is bounded
    by `max_pool` and the user refreshes after applying labels to surface
    the next batch.
    """
    pool_rows = (
        await db.execute(
            select(
                DetectionModel.id,
                DetectionModel.face_embedding,
                DetectionModel.object_embedding,
                DetectionModel.bbox,
                DetectionModel.frame_id,
                DetectionModel.subclass_id,
                DetectionModel.source,
                DetectionModel.reviewed,
                DetectionModel.reviewed_at,
                DetectionModel.created_at,
                Frame.path.label("frame_path"),
                Frame.clip_id,
            )
            .select_from(DetectionModel)
            .join(Frame, Frame.id == DetectionModel.frame_id)
            .where(
                DetectionModel.class_id == class_id,
                DetectionModel.reviewed.is_(False),
                DetectionModel.subclass_id.is_(None),
                DetectionModel.deleted_at.is_(None),
                Frame.kept.is_(True),
                (DetectionModel.face_embedding.is_not(None))
                | (DetectionModel.object_embedding.is_not(None)),
            )
            .order_by(DetectionModel.created_at)
            .limit(max_pool + 1)
        )
    ).all()

    pool_truncated = len(pool_rows) > max_pool
    pool_rows = pool_rows[:max_pool]
    pool_size = len(pool_rows)

    rows_by_id = {row.id: row for row in pool_rows}
    face_count = sum(1 for r in pool_rows if r.face_embedding is not None)
    object_count = sum(1 for r in pool_rows if r.object_embedding is not None)
    if face_count and object_count:
        embedding_kind: EmbeddingKind = "mixed"
    elif face_count:
        embedding_kind = "face"
    else:
        embedding_kind = "object"

    def _to_item(row: Any) -> DetectionGalleryItem:
        return DetectionGalleryItem(
            id=row.id,
            frame_id=row.frame_id,
            clip_id=row.clip_id,
            class_id=class_id,
            subclass_id=row.subclass_id,
            bbox=Bbox(**row.bbox),
            image_url=f"/files/frames/{row.frame_path}" if row.frame_path else None,
            crop_url=crop_url(str(row.id)) if row.frame_path else None,
            source=row.source,
            reviewed=row.reviewed,
            reviewed_at=row.reviewed_at,
            created_at=row.created_at,
        )

    # Oldest-first so the seed sequence is stable across requests. As clusters
    # form, members are removed from the remaining set — subsequent seeds skip
    # any detection already clustered.
    remaining: list[uuid.UUID] = [row.id for row in pool_rows]
    clusters: list[SimilarityCluster] = []

    while remaining and len(clusters) < max_clusters:
        seed_id = remaining[0]
        seed_row = rows_by_id[seed_id]
        # Same dispatch rule as `_assign_subclass_async`: face beats object
        # when both are present.
        if seed_row.face_embedding is not None:
            emb_col = DetectionModel.face_embedding
            seed_vec = seed_row.face_embedding
        else:
            emb_col = DetectionModel.object_embedding
            seed_vec = seed_row.object_embedding

        distance = emb_col.cosine_distance(seed_vec)
        neighbor_pool = [d for d in remaining if d != seed_id]
        member_ids: list[uuid.UUID] = [seed_id]
        avg_distance = 0.0

        if neighbor_pool and cluster_size > 1:
            neighbor_rows = (
                await db.execute(
                    select(DetectionModel.id, distance.label("d"))
                    .where(
                        DetectionModel.id.in_(neighbor_pool),
                        emb_col.is_not(None),
                    )
                    .order_by(distance)
                    .limit(cluster_size - 1)
                )
            ).all()
            if neighbor_rows:
                member_ids.extend(nid for nid, _ in neighbor_rows)
                avg_distance = sum(float(d) for _, d in neighbor_rows) / len(neighbor_rows)

        members = [_to_item(rows_by_id[mid]) for mid in member_ids]
        clusters.append(
            SimilarityCluster(
                seed_id=seed_id,
                avg_distance=avg_distance,
                members=members,
            )
        )
        clustered = set(member_ids)
        remaining = [d for d in remaining if d not in clustered]

    return SimilarityClustersResponse(
        clusters=clusters,
        embedding_kind=embedding_kind,
        pool_size=pool_size,
        pool_truncated=pool_truncated,
        remaining=len(remaining),
    )


@router.post("/bulk-review", response_model=BulkReviewResponse)
async def bulk_review(
    payload: BulkReviewRequest,
    db: AsyncSession = Depends(get_db),
) -> BulkReviewResponse:
    """Apply class/subclass/review changes to many detections in one shot.

    Unified-apply semantics: pass any subset of `{class_id, subclass_id,
    reviewed}` — each row's audit reason is inferred from what actually
    changes on that row (mirrors the per-detection PATCH inference). Skips
    soft-deleted rows and rows where the selected sub-class would belong to a
    different class than the detection (caller can include `class_id` in the
    same call to override). Idempotent: a re-apply with the same values
    writes zero audits.
    """
    data = payload.model_dump(exclude_unset=True)
    has_class = "class_id" in data
    has_subclass = "subclass_id" in data
    has_reviewed = "reviewed" in data

    target_subclass: Subclass | None = None
    if has_subclass and data["subclass_id"] is not None:
        target_subclass = await db.get(Subclass, data["subclass_id"])
        if target_subclass is None:
            raise HTTPException(status_code=404, detail="Sub-class not found")
        if has_class and data["class_id"] not in (None, target_subclass.class_id):
            raise HTTPException(
                status_code=409,
                detail="Sub-class belongs to a different class than class_id",
            )

    detections = list(
        await db.scalars(
            select(DetectionModel).where(
                DetectionModel.id.in_(payload.detection_ids),
                DetectionModel.deleted_at.is_(None),
            )
        )
    )

    now = datetime.now(UTC)
    updated = 0
    audits_written = 0
    affected_class_ids: set[uuid.UUID | None] = set()
    affected_frame_ids: set[uuid.UUID] = set()

    for det in detections:
        # If the caller is only changing the subclass but the detection's
        # class doesn't match the subclass's class, the row would become
        # internally inconsistent — skip it rather than write garbage.
        if (
            target_subclass is not None
            and not has_class
            and det.class_id != target_subclass.class_id
        ):
            continue

        class_changed = has_class and data["class_id"] != det.class_id
        subclass_changed = has_subclass and data["subclass_id"] != det.subclass_id
        row_changed = False

        if class_changed or subclass_changed:
            db.add(
                make_audit(
                    det,
                    reason="user_reassign",
                    from_class_id=det.class_id,
                    to_class_id=data["class_id"] if class_changed else det.class_id,
                    from_subclass_id=det.subclass_id,
                    to_subclass_id=data["subclass_id"] if subclass_changed else det.subclass_id,
                )
            )
            audits_written += 1
            if class_changed:
                det.class_id = data["class_id"]
            if subclass_changed:
                det.subclass_id = data["subclass_id"]
            row_changed = True

        if has_reviewed:
            if data["reviewed"] and not det.reviewed:
                det.reviewed = True
                det.reviewed_at = now
                db.add(make_audit(det, reason="user_review", to_class_id=det.class_id))
                audits_written += 1
                row_changed = True
            elif data["reviewed"] is False and det.reviewed:
                det.reviewed = False
                det.reviewed_at = None
                row_changed = True

        if row_changed:
            updated += 1
            affected_class_ids.add(det.class_id)
            affected_frame_ids.add(det.frame_id)

    await db.commit()

    if affected_frame_ids:
        # One SSE per affected frame so any open `/labeling/:fid` view refreshes.
        clip_rows = await db.execute(
            select(Frame.id, Frame.clip_id).where(Frame.id.in_(affected_frame_ids))
        )
        for frame_id, clip_id in clip_rows:
            await publish("frame.updated", clip_id=str(clip_id), frame_id=str(frame_id))
    if affected_class_ids:
        await maybe_trigger_training(db, affected_class_ids)

    return BulkReviewResponse(
        updated=updated,
        skipped=len(payload.detection_ids) - updated,
        audits_written=audits_written,
        affected_frame_ids=list(affected_frame_ids),
    )

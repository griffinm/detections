"""`vd.assign_track_subclass` — track-level sub-class vote across member detections.

Runs as the per-detection embedding pipeline's last leg whenever the detection
belongs to a track (the unchanged `vd.assign_subclass` handles loose
user-drawn boxes with no track). For each member detection that has an
embedding, run kNN — or the active per-class classifier — to get a
per-detection (subclass_id, confidence). Aggregate: most votes wins, ties
break on mean cosine similarity. If the winning mean similarity clears
`subclass_min_confidence`, we set it on the track and propagate to every
unreviewed model-source detection in the track.

The task fires once per member-detection embedding completion; the work is
idempotent because we only write an audit row when the winning sub-class
actually changes from what's already on the row.
"""

import asyncio
import uuid

from sqlalchemy import func, select

from vd_db import knn_subclass, load_effective_settings, resolve_model_path
from vd_db.models import (
    DetectionAudit,
    DetectionModel,
    ModelVersion,
    Subclass,
    Track,
)
from vd_tasks.app import celery_app

from worker.db import db_session
from worker.events import publish


async def _assign_track_subclass_async(track_id: str) -> bool:
    tid = uuid.UUID(track_id)

    async with db_session() as session:
        settings = await load_effective_settings(session)
        track = await session.get(Track, tid)
        if track is None or track.deleted_at is not None or track.class_id is None:
            return False

        has_subclass = await session.scalar(
            select(func.count())
            .select_from(Subclass)
            .where(Subclass.class_id == track.class_id, Subclass.is_active.is_(True))
        )
        if not has_subclass:
            return False

        # Regime B: an active per-class classifier supersedes the kNN bootstrap.
        classifier_version = await session.scalar(
            select(ModelVersion).where(
                ModelVersion.kind == "classifier",
                ModelVersion.target_class_id == track.class_id,
                ModelVersion.is_active.is_(True),
            )
        )

        members = list(
            await session.scalars(
                select(DetectionModel)
                .where(
                    DetectionModel.track_id == tid,
                    DetectionModel.deleted_at.is_(None),
                    DetectionModel.class_id == track.class_id,
                )
                .order_by(DetectionModel.created_at)
            )
        )
        if not members:
            return False

        # Per-detection vote: (subclass_id, confidence) for each member with
        # an embedding. Face wins over object when both are present, matching
        # `vd.assign_subclass`.
        votes: list[tuple[uuid.UUID, float]] = []
        for det in members:
            if det.face_embedding is not None:
                query_vec, use_face = det.face_embedding, True
            elif det.object_embedding is not None:
                query_vec, use_face = det.object_embedding, False
            else:
                continue

            if classifier_version is not None:
                from vd_ml import load_classifier, predict_subclass

                classifier = load_classifier(
                    str(resolve_model_path(settings.models_dir, classifier_version.weights_path))
                )
                subclass_id_str, confidence = predict_subclass(
                    classifier, list(query_vec)
                )
                subclass_id = uuid.UUID(subclass_id_str)
                still_active = await session.scalar(
                    select(Subclass.id).where(
                        Subclass.id == subclass_id, Subclass.is_active.is_(True)
                    )
                )
                if still_active is None:
                    continue
            else:
                match = await knn_subclass(
                    session, track.class_id, det.id, query_vec, use_face
                )
                if match is None:
                    continue
                subclass_id, confidence = match
            votes.append((subclass_id, confidence))

        if not votes:
            return False

        # Aggregate: bucket by sub-class, majority wins, ties broken on mean
        # cosine sim. Confidence = mean of the winning bucket's votes.
        buckets: dict[uuid.UUID, list[float]] = {}
        for sid, conf in votes:
            buckets.setdefault(sid, []).append(conf)
        winner = max(
            buckets,
            key=lambda sid: (len(buckets[sid]), sum(buckets[sid]) / len(buckets[sid])),
        )
        winning_confidence = sum(buckets[winner]) / len(buckets[winner])
        if winning_confidence < settings.subclass_min_confidence:
            return False

        audit_model_version_id = (
            classifier_version.id if classifier_version is not None
            else track.model_version_id
        )

        # Track-level write. Only audit + publish if the assignment actually
        # changes, so re-runs (one per embedding completion) stay quiet.
        changed = (
            track.predicted_subclass_id != winner
            or track.subclass_id != winner
        )
        track.predicted_subclass_id = winner
        track.confidence_subclass = winning_confidence
        if not track.reviewed:
            track.subclass_id = winner

        # Propagate to unreviewed model-source members. Per-detection audits
        # carry the assignment in the existing ledger so accuracy queries don't
        # need to learn about tracks for Stage A.
        for det in members:
            if det.reviewed or det.source != "model":
                continue
            if det.subclass_id == winner and det.predicted_subclass_id == winner:
                continue
            det.predicted_subclass_id = winner
            det.subclass_id = winner
            det.confidence_subclass = winning_confidence
            session.add(
                DetectionAudit(
                    detection_id=det.id,
                    to_subclass_id=winner,
                    reason="initial_prediction",
                    model_version_id=audit_model_version_id,
                )
            )

        clip_id = track.clip_id
        await session.commit()

    if changed:
        await publish("clip.tracks_updated", clip_id=str(clip_id), track_id=str(tid))
    return True


@celery_app.task(name="vd.assign_track_subclass", bind=True, max_retries=3)
def assign_track_subclass(self, track_id: str) -> bool:  # type: ignore[misc]
    try:
        return asyncio.run(_assign_track_subclass_async(track_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10) from exc

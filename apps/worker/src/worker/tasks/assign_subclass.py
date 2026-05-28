"""`vd.assign_subclass` — kNN sub-class assignment over `subclass_examples`.

Regime A (bootstrap kNN). The detection's embedding is matched against the
user-curated example detections of the same class: top-5 nearest, majority
vote, tie-break on mean cosine similarity. A winner above
`subclass_min_confidence` is recorded as the prediction and — unless the
detection has already been user-reviewed — as the current assignment.

Pure compute; safe to re-run.
"""

import asyncio
import uuid

from sqlalchemy import func, select

from vd_db import knn_subclass, load_effective_settings, resolve_model_path
from vd_db.models import (
    DetectionAudit,
    DetectionModel,
    Frame,
    ModelVersion,
    Subclass,
)
from vd_tasks.app import celery_app

from worker.db import db_session
from worker.events import publish


async def _assign_subclass_async(detection_id: str) -> bool:
    det_id = uuid.UUID(detection_id)

    async with db_session() as session:
        settings = await load_effective_settings(session)
        detection = await session.get(DetectionModel, det_id)
        if (
            detection is None
            or detection.deleted_at is not None
            or detection.class_id is None
        ):
            return False

        has_subclass = await session.scalar(
            select(func.count())
            .select_from(Subclass)
            .where(Subclass.class_id == detection.class_id, Subclass.is_active.is_(True))
        )
        if not has_subclass:
            return False

        if detection.face_embedding is not None:
            query_vec, use_face = detection.face_embedding, True
        elif detection.object_embedding is not None:
            query_vec, use_face = detection.object_embedding, False
        else:
            return False

        # Regime B: an active per-class classifier supersedes the kNN bootstrap.
        classifier_version = await session.scalar(
            select(ModelVersion).where(
                ModelVersion.kind == "classifier",
                ModelVersion.target_class_id == detection.class_id,
                ModelVersion.is_active.is_(True),
            )
        )
        audit_model_version_id = detection.model_version_id
        if classifier_version is not None:
            from vd_ml import load_classifier, predict_subclass

            classifier = load_classifier(
                str(resolve_model_path(settings.models_dir, classifier_version.weights_path))
            )
            subclass_id_str, confidence = predict_subclass(classifier, list(query_vec))
            subclass_id = uuid.UUID(subclass_id_str)
            audit_model_version_id = classifier_version.id
            # The classifier may name a sub-class deactivated since training.
            still_active = await session.scalar(
                select(Subclass.id).where(
                    Subclass.id == subclass_id, Subclass.is_active.is_(True)
                )
            )
            if still_active is None:
                return False
        else:
            match = await knn_subclass(
                session, detection.class_id, det_id, query_vec, use_face
            )
            if match is None:
                return False
            subclass_id, confidence = match

        if confidence < settings.subclass_min_confidence:
            return False

        detection.predicted_subclass_id = subclass_id
        detection.confidence_subclass = confidence
        if not detection.reviewed:
            detection.subclass_id = subclass_id
        session.add(
            DetectionAudit(
                detection_id=det_id,
                to_subclass_id=subclass_id,
                reason="initial_prediction",
                model_version_id=audit_model_version_id,
            )
        )
        frame_id = detection.frame_id
        clip_id = await session.scalar(select(Frame.clip_id).where(Frame.id == frame_id))
        await session.commit()

    if clip_id is not None:
        await publish("frame.updated", clip_id=str(clip_id), frame_id=str(frame_id))
    return True


@celery_app.task(name="vd.assign_subclass", bind=True, max_retries=3)
def assign_subclass(self, detection_id: str) -> bool:  # type: ignore[misc]
    try:
        return asyncio.run(_assign_subclass_async(detection_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10) from exc

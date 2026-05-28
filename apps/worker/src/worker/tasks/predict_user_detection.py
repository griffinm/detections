"""Predict a class for a user-drawn detection by running YOLO on the frame.

The labeling UI calls `POST /api/detections/{id}/predict` after the user
finishes drawing a box (debounced ~1 s so resizing settles first). This task
runs YOLO on the **full** frame (not the crop — YOLO is trained with context),
matches the best-IoU box against the user's bbox, and writes the prediction
back. If the user didn't pre-select a class, the predicted class is also
auto-assigned so it lights up in the picker; if they did, only the prediction
chip updates and the user's choice wins.
"""

import asyncio
import uuid

from sqlalchemy import select

from vd_db import load_effective_settings, resolve_model_path
from vd_db.models import Class, DetectionAudit, DetectionModel, Frame, Subclass
from vd_tasks.app import celery_app

from worker.db import db_session
from worker.events import publish

# Below this overlap we consider YOLO to have missed the box entirely.
# 0.3 is loose enough to tolerate sloppy user-drawn corners but tight enough
# that a nearby unrelated object doesn't get mis-attributed.
MIN_PREDICTION_IOU = 0.3


async def _predict_user_detection_async(detection_id: str) -> bool:
    # Imported lazily: the cpu worker autodiscovers this module to register
    # the task but never runs it and lacks the gpu deps.
    from vd_ml import iou, load_yolo, predict_batch

    from worker.models import get_or_register_yolo

    det_id = uuid.UUID(detection_id)

    async with db_session() as session:
        detection = await session.get(DetectionModel, det_id)
        # A predict request can race with a delete (undo) or with the box
        # being a model-source row; in either case there's nothing to do.
        if (
            detection is None
            or detection.deleted_at is not None
            or detection.source != "user"
        ):
            return False

        frame = await session.get(Frame, detection.frame_id)
        if frame is None or frame.path is None:
            return False

        settings = await load_effective_settings(session)
        file_path = settings.frames_dir / frame.path
        if not file_path.exists():
            # Frame got pruned between draw and predict — bail without erroring.
            return False

        version = await get_or_register_yolo(session, settings)
        model = load_yolo(
            str(resolve_model_path(settings.models_dir, version.weights_path))
        )

        kept_classes = list(
            await session.scalars(
                select(Class).where(
                    Class.yolo_class_index.is_not(None), Class.is_active.is_(True)
                )
            )
        )
        index_to_class: dict[int, uuid.UUID] = {
            int(cls.yolo_class_index): cls.id for cls in kept_classes
        }
        person_class_ids = {cls.id for cls in kept_classes if cls.name == "person"}
        subclassed_class_ids = set(
            await session.scalars(
                select(Subclass.class_id).where(Subclass.is_active.is_(True)).distinct()
            )
        )

        results = predict_batch(
            model, [file_path], settings.detection_min_confidence
        )
        per_frame_boxes = results[0] if results else []

        # Best IoU match against the user's bbox, restricted to YOLO classes
        # we keep (others are not selectable in the UI anyway).
        best_iou = 0.0
        best_class_id: uuid.UUID | None = None
        best_score: float | None = None
        for box in per_frame_boxes:
            class_id = index_to_class.get(box.class_index)
            if class_id is None:
                continue
            overlap = iou(detection.bbox, box.bbox)
            if overlap > best_iou:
                best_iou = overlap
                best_class_id = class_id
                best_score = float(box.score)

        if best_iou < MIN_PREDICTION_IOU:
            best_class_id = None
            best_score = None

        detection.predicted_class_id = best_class_id
        if best_score is not None:
            detection.confidence_class = best_score
        # Auto-assign the class only when the user hadn't already chosen one —
        # their choice always wins over the model.
        auto_assigned = False
        if best_class_id is not None and detection.class_id is None:
            detection.class_id = best_class_id
            auto_assigned = True
        detection.model_version_id = version.id

        session.add(
            DetectionAudit(
                detection_id=detection.id,
                reason="initial_prediction",
                to_class_id=best_class_id,
                model_version_id=version.id,
            )
        )
        await session.commit()
        await session.refresh(detection)

        # Capture what we need before the session closes.
        final_class_id = detection.class_id
        frame_clip_id = frame.clip_id
        frame_id = frame.id

    # Chain embedding for sub-class prediction so a freshly-auto-assigned box
    # behaves like a YOLO-detected one (the embed task then chains assign_subclass).
    # Skip if the user already had it classified — they may have done so before
    # the predict ran, and the existing edit path enqueues embedding on
    # promote-example; we don't want to double-fire.
    if auto_assigned and final_class_id is not None:
        if final_class_id in person_class_ids:
            celery_app.send_task(
                "vd.recognize_face", args=[str(det_id)], queue="gpu"
            )
        elif final_class_id in subclassed_class_ids:
            celery_app.send_task(
                "vd.embed_object", args=[str(det_id)], queue="gpu"
            )

    await publish(
        "frame.updated", clip_id=str(frame_clip_id), frame_id=str(frame_id)
    )
    return True


@celery_app.task(name="vd.predict_user_detection", bind=True, max_retries=3)
def predict_user_detection(self, detection_id: str) -> bool:  # type: ignore[misc]
    try:
        return asyncio.run(_predict_user_detection_async(detection_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10) from exc

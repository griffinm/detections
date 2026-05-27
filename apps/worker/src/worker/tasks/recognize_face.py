"""`vd.recognize_face` — embed the face on a person detection (InsightFace).

Runs on every `person` detection regardless of whether any sub-class exists:
ArcFace embeddings are cheap and we always want them ready for later kNN.
Idempotent — skips a detection that already has a `face_embedding`.
"""

import asyncio
import uuid

from vd_db.models import DetectionModel, Frame
from vd_settings import Settings
from vd_tasks.app import celery_app

from worker.crops import crop_detection
from worker.db import db_session


async def _recognize_face_async(detection_id: str) -> bool:
    # Imported here, not at module scope: the cpu worker autodiscovers this
    # module to register the task but never runs it, and lacks the gpu deps.
    import numpy as np

    from vd_ml import detect_and_embed, load_face_app

    settings = Settings()
    det_id = uuid.UUID(detection_id)

    async with db_session() as session:
        detection = await session.get(DetectionModel, det_id)
        if detection is None or detection.deleted_at is not None:
            return False
        if detection.face_embedding is not None:
            return False
        frame = await session.get(Frame, detection.frame_id)
        if frame is None:
            return False
        crop = crop_detection(settings.frames_dir, frame, detection)
        if crop is None:
            return False

        app = load_face_app(
            settings.insightface_pack, str(settings.models_dir / "insightface")
        )
        image_bgr = np.ascontiguousarray(np.asarray(crop)[:, :, ::-1])
        embedding = detect_and_embed(app, image_bgr)
        if embedding is None:
            return False  # no face found inside the person crop

        detection.face_embedding = embedding
        track_id = detection.track_id
        await session.commit()

    if track_id is not None:
        celery_app.send_task(
            "vd.assign_track_subclass", args=[str(track_id)], queue="gpu"
        )
    else:
        celery_app.send_task("vd.assign_subclass", args=[detection_id], queue="gpu")
    return True


@celery_app.task(name="vd.recognize_face", bind=True, max_retries=3)
def recognize_face(self, detection_id: str) -> bool:  # type: ignore[misc]
    try:
        return asyncio.run(_recognize_face_async(detection_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10) from exc

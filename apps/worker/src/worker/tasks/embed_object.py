"""`vd.embed_object` — embed a non-person detection crop with DINOv2.

Scheduled for a detection whose class has at least one active sub-class. The
embedding is stored even if no examples exist yet; `vd.assign_subclass` simply
no-ops until examples appear. Idempotent — skips an existing `object_embedding`.
"""

import asyncio
import uuid

from vd_db.models import DetectionModel, Frame
from vd_settings import Settings
from vd_tasks.app import celery_app

from worker.crops import crop_detection
from worker.db import db_session


async def _embed_object_async(detection_id: str) -> bool:
    # Imported here, not at module scope: the cpu worker lacks the gpu deps.
    from vd_ml import embed_crop, load_dino

    settings = Settings()
    det_id = uuid.UUID(detection_id)

    async with db_session() as session:
        detection = await session.get(DetectionModel, det_id)
        if detection is None or detection.deleted_at is not None:
            return False
        if detection.object_embedding is not None:
            return False
        frame = await session.get(Frame, detection.frame_id)
        if frame is None:
            return False
        crop = crop_detection(settings.frames_dir, frame, detection)
        if crop is None:
            return False

        dino = load_dino(cache_dir=str(settings.models_dir / "hf"))
        detection.object_embedding = embed_crop(dino, crop)
        await session.commit()

    celery_app.send_task("vd.assign_subclass", args=[detection_id], queue="gpu")
    return True


@celery_app.task(name="vd.embed_object", bind=True, max_retries=3)
def embed_object(self, detection_id: str) -> bool:  # type: ignore[misc]
    try:
        return asyncio.run(_embed_object_async(detection_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10) from exc

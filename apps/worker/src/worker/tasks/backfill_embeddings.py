"""`vd.backfill_embeddings` — retroactively embed + assign a class's detections.

Triggered when the first active sub-class is created for a class (or manually
re-run). Detections that already carry the relevant embedding only need
re-assignment; detections without one are fanned out to `recognize_face` /
`embed_object`, which chain into `assign_subclass` themselves. This is what
lets clips ingested *before* a sub-class existed still get auto-assigned.
"""

import asyncio
import uuid

from sqlalchemy import select

from vd_db.models import Class, DetectionModel
from vd_tasks.app import celery_app

from worker.db import db_session


async def _backfill_embeddings_async(class_id: str) -> int:
    cid = uuid.UUID(class_id)

    async with db_session() as session:
        cls = await session.get(Class, cid)
        if cls is None:
            return 0
        use_face = cls.name == "person"
        emb = (
            DetectionModel.face_embedding if use_face else DetectionModel.object_embedding
        )
        scope = (DetectionModel.class_id == cid, DetectionModel.deleted_at.is_(None))
        need_embed = list(
            await session.scalars(select(DetectionModel.id).where(*scope, emb.is_(None)))
        )
        have_embed = list(
            await session.scalars(select(DetectionModel.id).where(*scope, emb.is_not(None)))
        )

    embed_task = "vd.recognize_face" if use_face else "vd.embed_object"
    for det_id in need_embed:
        celery_app.send_task(embed_task, args=[str(det_id)], queue="gpu")
    for det_id in have_embed:
        celery_app.send_task("vd.assign_subclass", args=[str(det_id)], queue="gpu")
    return len(need_embed) + len(have_embed)


@celery_app.task(name="vd.backfill_embeddings", bind=True, max_retries=3)
def backfill_embeddings(self, class_id: str) -> int:  # type: ignore[misc]
    try:
        return asyncio.run(_backfill_embeddings_async(class_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10) from exc

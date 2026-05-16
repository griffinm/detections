import asyncio
import uuid
from pathlib import Path

from sqlalchemy import func, select

from vd_db import load_effective_settings
from vd_db.models import Class, Clip, DetectionAudit, DetectionModel, Frame, Subclass
from vd_tasks.app import celery_app

from worker.db import db_session
from worker.events import publish


async def _detect_frame_batch_async(frame_ids: list[str]) -> int:
    # Imported here, not at module scope: the cpu worker autodiscovers this
    # module to register the task but never runs it, and lacks the gpu deps.
    from vd_ml import load_yolo, predict_batch

    from worker.models import get_or_register_yolo

    fids = [uuid.UUID(f) for f in frame_ids]

    async with db_session() as session:
        settings = await load_effective_settings(session)
        # Skip frames already detected — makes the task safely re-runnable.
        frames = list(
            await session.scalars(
                select(Frame).where(Frame.id.in_(fids), Frame.detect_status == "pending")
            )
        )
        if not frames:
            return 0

        version = await get_or_register_yolo(session, settings)
        model = load_yolo(version.weights_path)

        # YOLO class index -> class_id, restricted to the builtin classes we keep.
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
        # Classes with ≥1 active sub-class want a DINOv2 object embedding.
        subclassed_class_ids = set(
            await session.scalars(
                select(Subclass.class_id).where(Subclass.is_active.is_(True)).distinct()
            )
        )

        # Resolve on-disk JPEGs; a frame whose file is gone is treated as empty.
        loadable: list[Frame] = []
        paths: list[Path] = []
        for frame in frames:
            if frame.path is None:
                continue
            file_path = settings.frames_dir / frame.path
            if file_path.exists():
                loadable.append(frame)
                paths.append(file_path)

        results = (
            predict_batch(model, paths, settings.detection_min_confidence) if paths else []
        )
        per_frame = dict(zip(loadable, results, strict=True))

        clip_ids: set[uuid.UUID] = set()
        new_detections: list[DetectionModel] = []
        for frame in frames:
            clip_ids.add(frame.clip_id)
            kept_any = False
            for box in per_frame.get(frame, []):
                class_id = index_to_class.get(box.class_index)
                if class_id is None:  # COCO class outside our builtins — drop it.
                    continue
                kept_any = True
                detection = DetectionModel(
                    frame_id=frame.id,
                    class_id=class_id,
                    bbox=box.bbox,
                    confidence_class=box.score,
                    source="model",
                    model_version_id=version.id,
                    predicted_class_id=class_id,
                )
                detection.audits.append(
                    DetectionAudit(
                        to_class_id=class_id,
                        reason="initial_prediction",
                        model_version_id=version.id,
                    )
                )
                session.add(detection)
                new_detections.append(detection)
            frame.detect_status = "done"
            if not kept_any:
                frame.kept = False
        await session.commit()

        # Mark clips whose frames are all detected as done.
        finished: list[uuid.UUID] = []
        for clip_id in clip_ids:
            remaining = await session.scalar(
                select(func.count())
                .select_from(Frame)
                .where(Frame.clip_id == clip_id, Frame.detect_status == "pending")
            )
            if remaining:
                continue
            clip = await session.get(Clip, clip_id)
            if clip is not None and clip.status == "detecting":
                clip.status = "done"
                finished.append(clip_id)
        await session.commit()

    # Prune object-free frames on the cpu queue (deletes the JPEG).
    for frame in frames:
        if not frame.kept:
            celery_app.send_task("vd.prune_frame", args=[str(frame.id)], queue="cpu")

    # Phase 4: embed person faces (always) and sub-classed objects, then the
    # embed tasks chain into vd.assign_subclass themselves.
    for detection in new_detections:
        if detection.class_id in person_class_ids:
            celery_app.send_task("vd.recognize_face", args=[str(detection.id)], queue="gpu")
        elif detection.class_id in subclassed_class_ids:
            celery_app.send_task("vd.embed_object", args=[str(detection.id)], queue="gpu")

    for frame in frames:
        await publish(
            "frame.detect.done", clip_id=str(frame.clip_id), frame_id=str(frame.id)
        )
    for clip_id in finished:
        await publish("clip.status", clip_id=str(clip_id), status="done")
        await publish("clip.done", clip_id=str(clip_id))
    return len(frames)


@celery_app.task(name="vd.detect_frame_batch", bind=True, max_retries=3)
def detect_frame_batch(self, frame_ids: list[str]) -> int:  # type: ignore[misc]
    try:
        return asyncio.run(_detect_frame_batch_async(frame_ids))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10) from exc

import asyncio
import uuid
from pathlib import Path

from sqlalchemy import select, update

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

        # Every pending frame must have its JPEG on disk: extract writes it
        # before scheduling detection, and pruning only runs once detection
        # has marked the frame done. A missing file is therefore a real fault
        # — a misconfigured frames_dir, an unmounted volume — so fail loudly
        # and let the task retry, rather than silently recording the frame as
        # object-free (which would then prune it, destroying the source frame).
        paths: list[Path] = []
        for frame in frames:
            if frame.path is None:
                raise RuntimeError(f"frame {frame.id} has no stored path")
            file_path = settings.frames_dir / frame.path
            if not file_path.exists():
                raise RuntimeError(
                    f"frame {frame.id} JPEG missing at {file_path} — check "
                    "VD_FRAMES_DIR and the frames volume mount"
                )
            paths.append(file_path)

        results = predict_batch(model, paths, settings.detection_min_confidence)
        per_frame = dict(zip(frames, results, strict=True))

        clip_ids: set[uuid.UUID] = set()
        new_detections: list[DetectionModel] = []
        for frame in frames:
            clip_ids.add(frame.clip_id)
            for box in per_frame.get(frame, []):
                class_id = index_to_class.get(box.class_index)
                if class_id is None:  # COCO class outside our builtins — drop it.
                    continue
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
        # Frames with zero detections stay kept=True: YOLO can miss things, and
        # the labeling UI lets the user add a box manually. Only dedup flips
        # kept=False (and unlinks the JPEG) for redundant near-duplicates.
        await session.commit()

        # Mark clips whose frames are all detected as done. A single
        # conditional UPDATE keeps this correct when batches for one clip run
        # concurrently: the `status == 'detecting'` guard means exactly one
        # batch flips the clip, and rowcount tells us which — a read-then-write
        # check would let two batches both see zero pending and double-fire.
        finished: list[uuid.UUID] = []
        for clip_id in clip_ids:
            still_pending = (
                select(Frame.id)
                .where(Frame.clip_id == clip_id, Frame.detect_status == "pending")
                .exists()
            )
            result = await session.execute(
                update(Clip)
                .where(Clip.id == clip_id, Clip.status == "detecting", ~still_pending)
                .values(status="done")
            )
            if result.rowcount == 1:
                finished.append(clip_id)
        await session.commit()

        # External-job callbacks (spec 04 §Jobs): a finished clip submitted via
        # POST /api/jobs needs its result delivered, and so does any clip whose
        # bytes deduped onto it. Duplicate clips share the canonical clip's
        # lifecycle, so flip them to `done` here too.
        callback_targets: list[uuid.UUID] = []
        for clip_id in finished:
            main = await session.get(Clip, clip_id)
            if main is not None and main.callback_url:
                callback_targets.append(clip_id)
            for dup in await session.scalars(
                select(Clip).where(Clip.canonical_clip_id == clip_id)
            ):
                dup.status = "done"
                if dup.callback_url:
                    callback_targets.append(dup.id)
        await session.commit()

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
        # Off the critical path: collapse near-duplicate frames now that every
        # frame of the clip has its detections. The clip is already `done`.
        celery_app.send_task("vd.dedup_clip_frames", args=[str(clip_id)], queue="cpu")
    for clip_id in callback_targets:
        celery_app.send_task(
            "vd.deliver_callback", args=[str(clip_id), "clip.done"], queue="cpu"
        )
    return len(frames)


@celery_app.task(name="vd.detect_frame_batch", bind=True, max_retries=3)
def detect_frame_batch(self, frame_ids: list[str]) -> int:  # type: ignore[misc]
    try:
        return asyncio.run(_detect_frame_batch_async(frame_ids))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10) from exc

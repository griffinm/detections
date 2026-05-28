"""`vd.detect_and_track_clip` — per-clip YOLO detection + BoT-SORT tracking.

Replaces the per-batch `vd.detect_frame_batch`: the tracker needs frame order
and accumulates state across the whole clip, so one task processes one clip.
For each frame it inserts `detections` rows (same audit ledger, same chained
`recognize_face` / `embed_object`); each detection's `track_id` is set to the
`tracks` row that maps to the tracker-assigned integer id (or NULL if the
tracker didn't link the box). Sub-class assignment then runs at the track
level — see `vd.assign_track_subclass`.
"""

import asyncio
import uuid
from collections import Counter
from pathlib import Path

from sqlalchemy import select, update

from vd_db import load_effective_settings, resolve_model_path
from vd_db.models import (
    Class,
    Clip,
    DetectionAudit,
    DetectionModel,
    Frame,
    Subclass,
    Track,
    TrackAudit,
)
from vd_tasks.app import celery_app

from worker.db import db_session
from worker.events import publish


async def _detect_and_track_clip_async(clip_id: str) -> int:
    # Imported here, not at module scope: the cpu worker autodiscovers this
    # module to register the task but never runs it, and lacks the gpu deps.
    from vd_ml import detect_and_track, load_yolo

    from worker.models import get_or_register_yolo

    cid = uuid.UUID(clip_id)

    async with db_session() as session:
        settings = await load_effective_settings(session)
        clip = await session.get(Clip, cid)
        if clip is None:
            return 0

        frames = list(
            await session.scalars(
                select(Frame)
                .where(
                    Frame.clip_id == cid,
                    Frame.kept.is_(True),
                    Frame.detect_status == "pending",
                )
                .order_by(Frame.frame_index)
            )
        )
        version = None
        results: list[list] = []
        paths: list[Path] = []
        if frames:
            version = await get_or_register_yolo(session, settings)
            model = load_yolo(
                str(resolve_model_path(settings.models_dir, version.weights_path))
            )

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

            results = detect_and_track(
                model,
                paths,
                settings.detection_min_confidence,
                tracker_config=settings.tracker,
            )

        # Build the per-clip context once.
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

        # Lazily materialise Track rows as the tracker emits new ids. The map
        # is per-clip — track ids from BoT-SORT are local to this call.
        tracker_to_track: dict[int, Track] = {}
        track_classes: dict[uuid.UUID, list[uuid.UUID]] = {}
        track_confs: dict[uuid.UUID, list[float]] = {}
        new_detections: list[DetectionModel] = []

        for frame, boxes in zip(frames, results, strict=True):
            for box in boxes:
                class_id = index_to_class.get(box.class_index)
                if class_id is None:
                    continue

                track_row: Track | None = None
                if box.track_id is not None:
                    track_row = tracker_to_track.get(box.track_id)
                    if track_row is None:
                        track_row = Track(
                            clip_id=cid,
                            source="tracker",
                            model_version_id=version.id if version else None,
                            first_frame_index=frame.frame_index,
                            last_frame_index=frame.frame_index,
                            n_detections=0,
                        )
                        session.add(track_row)
                        await session.flush()  # need track_row.id below
                        session.add(
                            TrackAudit(
                                track_id=track_row.id,
                                reason="initial",
                                model_version_id=version.id if version else None,
                            )
                        )
                        tracker_to_track[box.track_id] = track_row
                    else:
                        track_row.last_frame_index = frame.frame_index
                    track_row.n_detections += 1
                    track_classes.setdefault(track_row.id, []).append(class_id)
                    track_confs.setdefault(track_row.id, []).append(box.score)

                detection = DetectionModel(
                    frame_id=frame.id,
                    class_id=class_id,
                    bbox=box.bbox,
                    confidence_class=box.score,
                    source="model",
                    model_version_id=version.id if version else None,
                    predicted_class_id=class_id,
                    track_id=track_row.id if track_row is not None else None,
                )
                detection.audits.append(
                    DetectionAudit(
                        to_class_id=class_id,
                        reason="initial_prediction",
                        model_version_id=version.id if version else None,
                    )
                )
                session.add(detection)
                new_detections.append(detection)
            frame.detect_status = "done"

        # Track-level aggregates: majority class + mean confidence. The
        # majority is the predicted class too — they're identical until a user
        # reassigns the track in Stage B.
        for track_row in tracker_to_track.values():
            classes = track_classes.get(track_row.id, [])
            confs = track_confs.get(track_row.id, [])
            if classes:
                winner = Counter(classes).most_common(1)[0][0]
                track_row.class_id = winner
                track_row.predicted_class_id = winner
            if confs:
                track_row.confidence_class = sum(confs) / len(confs)
        await session.commit()

        # Mark the clip done. Same guard pattern as the old detect task — a
        # status='detecting' precondition prevents a re-run from re-firing the
        # completion side effects.
        result = await session.execute(
            update(Clip)
            .where(Clip.id == cid, Clip.status == "detecting")
            .values(status="done")
        )
        finished = result.rowcount == 1

        # External-job callbacks: a finished clip submitted via POST /api/jobs
        # needs its result delivered, and so do any clips whose bytes deduped
        # onto it. Duplicate clips share the canonical clip's lifecycle.
        callback_targets: list[uuid.UUID] = []
        if finished:
            main = await session.get(Clip, cid)
            if main is not None and main.callback_url:
                callback_targets.append(cid)
            for dup in await session.scalars(
                select(Clip).where(Clip.canonical_clip_id == cid)
            ):
                dup.status = "done"
                if dup.callback_url:
                    callback_targets.append(dup.id)
            await session.commit()

    for detection in new_detections:
        if detection.class_id in person_class_ids:
            celery_app.send_task("vd.recognize_face", args=[str(detection.id)], queue="gpu")
        elif detection.class_id in subclassed_class_ids:
            celery_app.send_task("vd.embed_object", args=[str(detection.id)], queue="gpu")

    for frame in frames:
        await publish(
            "frame.detect.done", clip_id=str(frame.clip_id), frame_id=str(frame.id)
        )
    if finished:
        await publish("clip.status", clip_id=str(cid), status="done")
        await publish("clip.done", clip_id=str(cid))
        celery_app.send_task("vd.dedup_clip_frames", args=[str(cid)], queue="cpu")
    for target in callback_targets:
        celery_app.send_task(
            "vd.deliver_callback", args=[str(target), "clip.done"], queue="cpu"
        )
    return len(frames)


async def _mark_clip_failed(clip_id: str, error: str) -> None:
    """Record a terminal detection failure on the clip and notify any external
    submitter.

    Without this a clip whose detection can't proceed — e.g. the active model's
    weights file is missing or unreadable — retries to death and then sits in
    `detecting` forever with an empty `error`, indistinguishable from in-flight
    work. Mirrors the terminal path in `vd.ingest_video`.
    """
    async with db_session() as session:
        clip = await session.get(Clip, uuid.UUID(clip_id))
        if clip is None or clip.status == "done":
            return
        clip.status = "failed"
        clip.error = error[:2000]
        callback_url = clip.callback_url
        await session.commit()
    await publish("clip.status", clip_id=clip_id, status="failed")
    if callback_url:
        celery_app.send_task(
            "vd.deliver_callback", args=[clip_id, "clip.failed"], queue="cpu"
        )


@celery_app.task(name="vd.detect_and_track_clip", bind=True, max_retries=3)
def detect_and_track_clip(self, clip_id: str) -> int:  # type: ignore[misc]
    try:
        return asyncio.run(_detect_and_track_clip_async(clip_id))
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=10) from exc
        asyncio.run(_mark_clip_failed(clip_id, str(exc)))
        raise

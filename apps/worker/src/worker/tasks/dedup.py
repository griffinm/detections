"""`vd.dedup_clip_frames` — collapse runs of near-identical frames in a clip.

At 1 FPS a static scene yields many visually identical frames; reviewing them
all is tedious and they N-times-inflate metrics. This task keeps one
representative per run of duplicates and prunes the rest.

A frame is a duplicate of the run's anchor only when *both* its perceptual
hash is within `frame_similarity_threshold` Hamming distance *and* its
detection set matches (same classes at the same rough positions) — so a frame
where something actually changed is never hidden.

`vd.backfill_frame_phash` is the one-off migration for frames extracted before
`frames.phash` was populated.
"""

import asyncio
import uuid
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import select

from vd_db import load_effective_settings
from vd_db.models import DetectionAudit, DetectionModel, Frame
from vd_tasks.app import celery_app

from worker.db import db_session
from worker.events import publish
from worker.phash import compute_phash, hamming

# Bbox-centre quantisation: two detections count as "same position" when their
# centres fall in the same 5%-of-frame cell. The tolerance for detection-aware
# duplicate matching.
_CENTRE_TOL = 0.05


def _signature(detections: list[DetectionModel]) -> tuple[tuple[str, int, int], ...]:
    """A position-aware fingerprint of a frame's detections.

    Sorted multiset of (class, quantised centre x, quantised centre y). Two
    frames with equal signatures hold the same objects in the same places.
    """
    sig = []
    for det in detections:
        b = det.bbox
        cx = b["x"] + b["w"] / 2
        cy = b["y"] + b["h"] / 2
        sig.append(
            (str(det.class_id), round(cx / _CENTRE_TOL), round(cy / _CENTRE_TOL))
        )
    return tuple(sorted(sig))


def _informativeness(detections: list[DetectionModel]) -> tuple[int, float]:
    """Rank key for picking a run's representative: detection count, then mean
    class confidence. `max()` keeps the first on a tie — the lowest
    `frame_index`, since runs are walked in order."""
    confs = [d.confidence_class for d in detections if d.confidence_class is not None]
    return len(detections), (sum(confs) / len(confs) if confs else 0.0)


async def _dedup_clip_frames_async(clip_id: str) -> int:
    cid = uuid.UUID(clip_id)
    pruned: list[uuid.UUID] = []

    async with db_session() as session:
        settings = await load_effective_settings(session)
        if not settings.prune_similar_frames:
            return 0
        threshold = settings.frame_similarity_threshold

        frames = list(
            await session.scalars(
                select(Frame)
                .where(
                    Frame.clip_id == cid,
                    Frame.kept.is_(True),
                    Frame.phash.is_not(None),
                )
                .order_by(Frame.frame_index)
            )
        )
        if len(frames) < 2:
            return 0

        detections = list(
            await session.scalars(
                select(DetectionModel).where(
                    DetectionModel.frame_id.in_([f.id for f in frames]),
                    DetectionModel.deleted_at.is_(None),
                )
            )
        )
        by_frame: dict[uuid.UUID, list[DetectionModel]] = defaultdict(list)
        for det in detections:
            by_frame[det.frame_id].append(det)
        sig = {f.id: _signature(by_frame[f.id]) for f in frames}

        # Group frame_index-adjacent frames into runs of mutual duplicates.
        # The anchor advances only when a frame breaks the run, so every run
        # member is a duplicate of one fixed frame — drift can't chain a run
        # across a slowly-changing scene.
        runs: list[list[Frame]] = []
        run = [frames[0]]
        anchor = frames[0]
        for frame in frames[1:]:
            is_dup = (
                hamming(frame.phash, anchor.phash) <= threshold
                and sig[frame.id] == sig[anchor.id]
            )
            if is_dup:
                run.append(frame)
            else:
                runs.append(run)
                run = [frame]
                anchor = frame
        runs.append(run)

        now = datetime.now(UTC)
        for run in runs:
            if len(run) == 1:
                continue
            representative = max(run, key=lambda f: _informativeness(by_frame[f.id]))
            for frame in run:
                if frame.id == representative.id:
                    continue
                dets = by_frame[frame.id]
                # Never prune a frame carrying ground truth.
                if any(d.reviewed or d.source == "user" for d in dets):
                    continue
                frame.kept = False
                for det in dets:
                    det.deleted_at = now
                    session.add(
                        DetectionAudit(
                            detection_id=det.id,
                            reason="user_delete",
                            from_class_id=det.class_id,
                            model_version_id=det.model_version_id,
                        )
                    )
                pruned.append(frame.id)
        await session.commit()
        kept = len(frames) - len(pruned)

    # Unlink the JPEGs of the pruned frames (force: a duplicate is always
    # redundant, regardless of `delete_frames_without_objects`).
    for fid in pruned:
        celery_app.send_task("vd.prune_frame", args=[str(fid), True], queue="cpu")
    await publish("clip.frames.deduped", clip_id=clip_id, pruned=len(pruned), kept=kept)
    return len(pruned)


async def _backfill_frame_phash_async(clip_id: str | None) -> int:
    """Populate `frames.phash` for frames extracted before the column was
    used, then re-run dedup on the affected clips."""
    hashed = 0
    affected: set[uuid.UUID] = set()

    async with db_session() as session:
        settings = await load_effective_settings(session)
        query = select(Frame).where(
            Frame.kept.is_(True),
            Frame.path.is_not(None),
            Frame.phash.is_(None),
        )
        if clip_id is not None:
            query = query.where(Frame.clip_id == uuid.UUID(clip_id))
        frames = list(
            await session.scalars(query.order_by(Frame.clip_id, Frame.frame_index))
        )

        for i, frame in enumerate(frames):
            assert frame.path is not None  # filtered above
            file_path = settings.frames_dir / frame.path
            if not file_path.exists():
                continue  # JPEG already purged — nothing to hash
            frame.phash = compute_phash(file_path)
            affected.add(frame.clip_id)
            hashed += 1
            if (i + 1) % 200 == 0:
                await session.commit()
        await session.commit()
        prune = settings.prune_similar_frames

    if prune:
        for cid in affected:
            celery_app.send_task("vd.dedup_clip_frames", args=[str(cid)], queue="cpu")
    return hashed


@celery_app.task(name="vd.dedup_clip_frames", bind=True, max_retries=3)
def dedup_clip_frames(self, clip_id: str) -> int:  # type: ignore[misc]
    try:
        return asyncio.run(_dedup_clip_frames_async(clip_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10) from exc


@celery_app.task(name="vd.backfill_frame_phash", bind=True, max_retries=3)
def backfill_frame_phash(self, clip_id: str | None = None) -> int:  # type: ignore[misc]
    try:
        return asyncio.run(_backfill_frame_phash_async(clip_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10) from exc

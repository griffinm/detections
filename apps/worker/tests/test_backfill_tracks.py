"""Integration tests for `vd.backfill_tracks`.

The chained `vd.detect_and_track_clip` task is stubbed so the test stays in
the worker process — we only verify the backfill task's destructive prep
(deleting unreviewed model detections + flipping frame status) is correct,
not the actual tracker run.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from vd_db.models import Class, Clip, DetectionModel, Frame, Track
from worker.tasks import backfill_tracks as bt_mod
from worker.tasks.backfill_tracks import _backfill_tracks_async


async def _seed_pre_p9_clip(session, *, with_reviewed=False, with_track=False):  # type: ignore[no-untyped-def]
    clip = Clip(
        filename="t.mp4", original_path="/in/t.mp4",
        sha256=uuid.uuid4().hex, size_bytes=1, status="done",
        processed_at=datetime.now(UTC), ingested_at=datetime.now(UTC),
    )
    session.add(clip)
    await session.flush()
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    frames = []
    for i in range(2):
        fr = Frame(
            clip_id=clip.id, frame_index=i, timestamp_sec=float(i),
            path=f"{clip.id}/f{i}.jpg", width=10, height=10,
            kept=True, detect_status="done",
        )
        session.add(fr)
        frames.append(fr)
    await session.flush()

    # One unreviewed model detection (should be reaped) + optionally one
    # reviewed model detection (must survive).
    model_unreviewed = DetectionModel(
        frame_id=frames[0].id, class_id=person, predicted_class_id=person,
        bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, source="model",
        confidence_class=0.5,
    )
    session.add(model_unreviewed)
    survivors = []
    if with_reviewed:
        model_reviewed = DetectionModel(
            frame_id=frames[1].id, class_id=person, predicted_class_id=person,
            bbox={"x": 0.2, "y": 0.2, "w": 0.2, "h": 0.2}, source="model",
            confidence_class=0.9, reviewed=True,
            reviewed_at=datetime.now(UTC),
        )
        session.add(model_reviewed)
        survivors.append(model_reviewed)
    user_drawn = DetectionModel(
        frame_id=frames[1].id, class_id=person,
        bbox={"x": 0.3, "y": 0.3, "w": 0.2, "h": 0.2}, source="user",
        reviewed=True, reviewed_at=datetime.now(UTC),
    )
    session.add(user_drawn)
    survivors.append(user_drawn)

    if with_track:
        track = Track(
            clip_id=clip.id, class_id=person, predicted_class_id=person,
            source="tracker", first_frame_index=0, last_frame_index=1,
            n_detections=1, confidence_class=0.9,
        )
        session.add(track)
        await session.flush()
    await session.commit()
    return clip, frames, model_unreviewed, survivors


@pytest.fixture
def stub_celery(monkeypatch: pytest.MonkeyPatch) -> list:
    """Capture scheduled celery tasks instead of dispatching them."""
    scheduled: list[tuple[str, list[object]]] = []

    def fake(name, args=None, **kw):  # type: ignore[no-untyped-def]
        scheduled.append((name, list(args or [])))

    monkeypatch.setattr(bt_mod.celery_app, "send_task", fake)
    return scheduled


async def test_backfill_reaps_only_unreviewed_model(session, stub_celery):  # type: ignore[no-untyped-def]
    clip, frames, model_unreviewed, survivors = await _seed_pre_p9_clip(
        session, with_reviewed=True
    )

    scheduled_count = await _backfill_tracks_async(str(clip.id), limit=10)
    assert scheduled_count == 1
    assert stub_celery == [("vd.detect_and_track_clip", [str(clip.id)])]

    session.expunge_all()
    # Unreviewed model detection gone; survivors kept (reviewed model + user).
    assert await session.get(DetectionModel, model_unreviewed.id) is None
    for s in survivors:
        refreshed = await session.get(DetectionModel, s.id)
        assert refreshed is not None and refreshed.deleted_at is None

    # Frames flipped back to pending for the re-detect pass.
    for fr in frames:
        refreshed = await session.get(Frame, fr.id)
        assert refreshed is not None and refreshed.detect_status == "pending"

    # Clip status reset to detecting so detect_and_track_clip will run.
    refreshed_clip = await session.get(Clip, clip.id)
    assert refreshed_clip is not None and refreshed_clip.status == "detecting"


async def test_backfill_is_idempotent_when_already_tracked(  # type: ignore[no-untyped-def]
    session, stub_celery,
):
    clip, _frames, _unreviewed, _survivors = await _seed_pre_p9_clip(
        session, with_track=True
    )

    scheduled = await _backfill_tracks_async(str(clip.id), limit=10)
    # Skipped (already has a live track) → no destructive reset, no enqueue.
    assert scheduled == 0
    assert stub_celery == []


async def test_backfill_sweep_walks_eligible_clips(session, stub_celery):  # type: ignore[no-untyped-def]
    a, *_ = await _seed_pre_p9_clip(session)
    b, *_ = await _seed_pre_p9_clip(session)
    _c, *_ = await _seed_pre_p9_clip(session, with_track=True)

    scheduled = await _backfill_tracks_async(None, limit=10)
    assert scheduled == 2
    queued = {args[0] for _name, args in stub_celery}
    assert queued == {str(a.id), str(b.id)}

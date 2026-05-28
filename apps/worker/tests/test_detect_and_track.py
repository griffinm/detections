"""Integration tests for `vd.detect_and_track_clip` against a real test database.

YOLO + tracker are faked (`load_yolo` / `detect_and_track` patched) so the test
is fast and deterministic; everything else — detection + track rows, the audit
ledger, clip completion, the chain to recognize_face/embed_object — runs for
real.
"""

import uuid
from types import SimpleNamespace

import pytest
import vd_ml
from sqlalchemy import select

from vd_db.models import (
    Class,
    Clip,
    DetectionAudit,
    DetectionModel,
    Frame,
    ModelVersion,
    Track,
)
from vd_ml import TrackedBox
from worker.tasks import detect_and_track as detect_mod
from worker.tasks.detect_and_track import _detect_and_track_clip_async


async def _seed(session, frames_dir, n_frames):  # type: ignore[no-untyped-def]
    clip = Clip(
        filename="t.mp4", original_path="/in/t.mp4",
        sha256=uuid.uuid4().hex, size_bytes=1, status="detecting",
    )
    session.add(clip)
    await session.flush()
    frames = []
    for i in range(n_frames):
        fr = Frame(
            clip_id=clip.id, frame_index=i, timestamp_sec=float(i),
            path=f"{clip.id}/frame_{i:06d}.jpg", width=640, height=480,
            kept=True, detect_status="pending",
        )
        session.add(fr)
        frames.append(fr)
    session.add(
        ModelVersion(kind="yolo", name="test-yolo", weights_path="/models/test.pt",
                     is_active=True)
    )
    await session.commit()
    for fr in frames:
        fp = frames_dir / fr.path
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_bytes(b"\xff\xd8\xff")  # content irrelevant — tracker is faked
    return clip, frames


@pytest.fixture
def capture_io(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Fake the YOLO + tracker calls; record published events and enqueued tasks."""
    events: list = []
    enqueued: list = []

    async def fake_publish(event_type, **kw):  # type: ignore[no-untyped-def]
        events.append((event_type, kw))

    def fake_send_task(name, args=None, **kw):  # type: ignore[no-untyped-def]
        enqueued.append((name, args))

    monkeypatch.setattr(detect_mod, "publish", fake_publish)
    monkeypatch.setattr(detect_mod.celery_app, "send_task", fake_send_task)
    monkeypatch.setattr(vd_ml, "load_yolo", lambda path: object())

    def set_results(boxes_by_index: dict[int, list[TrackedBox]]) -> None:
        def fake_track(model, paths, conf, tracker_config="botsort.yaml", device=0):  # type: ignore[no-untyped-def]
            return [boxes_by_index.get(int(p.stem.split("_")[1]), []) for p in paths]

        monkeypatch.setattr(vd_ml, "detect_and_track", fake_track)

    return SimpleNamespace(events=events, enqueued=enqueued, set_results=set_results)


async def test_detect_and_track_persists_tracks_and_detections(  # type: ignore[no-untyped-def]
    session, frames_dir, capture_io,
):
    person_id = await session.scalar(select(Class.id).where(Class.name == "person"))
    clip, frames = await _seed(session, frames_dir, n_frames=3)

    # Tracker id 1 spans frames 0+1 (one person walking through); tracker id
    # 2 appears only on frame 1; frame 2 has an untracked box. Class index 7
    # (truck) is not a builtin and is dropped.
    capture_io.set_results({
        0: [TrackedBox(class_index=0, score=0.9,
                       bbox={"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.4}, track_id=1)],
        1: [
            TrackedBox(class_index=0, score=0.85,
                       bbox={"x": 0.12, "y": 0.11, "w": 0.3, "h": 0.4}, track_id=1),
            TrackedBox(class_index=0, score=0.7,
                       bbox={"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2}, track_id=2),
            TrackedBox(class_index=7, score=0.6,
                       bbox={"x": 0.0, "y": 0.0, "w": 0.1, "h": 0.1}, track_id=3),
        ],
        2: [TrackedBox(class_index=0, score=0.6,
                       bbox={"x": 0.7, "y": 0.7, "w": 0.1, "h": 0.1}, track_id=None)],
    })

    n = await _detect_and_track_clip_async(str(clip.id))
    assert n == 3

    dets = list(await session.scalars(select(DetectionModel)))
    # Three person detections survive; the truck (class index 7) was dropped.
    assert len(dets) == 4
    assert all(d.class_id == person_id for d in dets)

    tracks = list(await session.scalars(select(Track)))
    # Two tracks survive: tracker id 1 (frames 0+1) and tracker id 2 (frame 1).
    # The untracked box on frame 2 has track_id NULL; the truck on frame 1
    # was dropped before a track row was needed.
    assert len(tracks) == 2
    by_n = sorted(tracks, key=lambda t: -t.n_detections)
    assert by_n[0].n_detections == 2
    assert by_n[0].first_frame_index == 0
    assert by_n[0].last_frame_index == 1
    assert by_n[1].n_detections == 1
    assert all(t.class_id == person_id and t.predicted_class_id == person_id
               for t in tracks)
    assert all(t.source == "tracker" for t in tracks)

    # Detections carry the right track_id (or NULL for the unassigned box).
    by_track = {t.id: [d for d in dets if d.track_id == t.id] for t in tracks}
    assert len(by_track[by_n[0].id]) == 2
    assert len(by_track[by_n[1].id]) == 1
    untracked = [d for d in dets if d.track_id is None]
    assert len(untracked) == 1
    assert untracked[0].confidence_class == pytest.approx(0.6)

    # Audit ledger: one initial_prediction per detection.
    audits = list(await session.scalars(select(DetectionAudit)))
    assert len(audits) == 4
    assert all(a.reason == "initial_prediction" for a in audits)

    # Clip done + completion broadcast.
    await session.refresh(clip)
    assert clip.status == "done"
    assert ("clip.done", {"clip_id": str(clip.id)}) in capture_io.events

    # Chain to recognize_face (person class), once per detection.
    chained = [name for name, _ in capture_io.enqueued if name == "vd.recognize_face"]
    assert len(chained) == 4


async def test_detect_and_track_raises_when_frame_jpeg_missing(  # type: ignore[no-untyped-def]
    session, frames_dir, capture_io,
):
    clip, frames = await _seed(session, frames_dir, n_frames=2)
    capture_io.set_results({})
    (frames_dir / frames[0].path).unlink()

    with pytest.raises(RuntimeError, match="JPEG missing"):
        await _detect_and_track_clip_async(str(clip.id))


async def test_detect_and_track_is_idempotent(  # type: ignore[no-untyped-def]
    session, frames_dir, capture_io,
):
    clip, frames = await _seed(session, frames_dir, n_frames=1)
    capture_io.set_results({
        0: [TrackedBox(class_index=0, score=0.9,
                       bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, track_id=10)],
    })

    assert await _detect_and_track_clip_async(str(clip.id)) == 1
    # Re-run: no pending frames remain, no duplicate detections or tracks created.
    assert await _detect_and_track_clip_async(str(clip.id)) == 0
    assert len(list(await session.scalars(select(DetectionModel)))) == 1
    assert len(list(await session.scalars(select(Track)))) == 1


async def test_mark_clip_failed_records_error_and_fires_callback(  # type: ignore[no-untyped-def]
    session, frames_dir, capture_io,
):
    clip, _ = await _seed(session, frames_dir, n_frames=1)
    clip.callback_url = "http://upstream/cb"
    await session.commit()

    await detect_mod._mark_clip_failed(str(clip.id), "boom")

    await session.refresh(clip)
    assert clip.status == "failed"
    assert clip.error == "boom"
    assert ("clip.status", {"clip_id": str(clip.id), "status": "failed"}) in capture_io.events
    assert ("vd.deliver_callback", [str(clip.id), "clip.failed"]) in capture_io.enqueued


async def test_mark_clip_failed_leaves_done_clip_untouched(  # type: ignore[no-untyped-def]
    session, frames_dir, capture_io,
):
    # A late terminal failure must not clobber a clip that already completed.
    clip, _ = await _seed(session, frames_dir, n_frames=1)
    clip.status = "done"
    await session.commit()

    await detect_mod._mark_clip_failed(str(clip.id), "late error")

    await session.refresh(clip)
    assert clip.status == "done"
    assert clip.error is None
    assert not any(name == "vd.deliver_callback" for name, _ in capture_io.enqueued)

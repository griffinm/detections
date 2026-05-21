"""Integration tests for `vd.detect_frame_batch` against a real test database.

The YOLO model is faked (`load_yolo` / `predict_batch` patched) so the test is
fast and deterministic; everything else — detection rows, the audit ledger,
clip completion — runs for real.
"""

import uuid
from types import SimpleNamespace

import pytest
import vd_ml
from sqlalchemy import select

from vd_db.models import Class, Clip, DetectionAudit, DetectionModel, Frame, ModelVersion
from vd_ml import Box
from worker.tasks import detect as detect_mod
from worker.tasks.detect import _detect_frame_batch_async


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
        fp.write_bytes(b"\xff\xd8\xff")  # content irrelevant — predict_batch is faked
    return clip, frames


@pytest.fixture
def capture_io(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Fake the YOLO calls; record published events and enqueued tasks."""
    events: list = []
    enqueued: list = []

    async def fake_publish(event_type, **kw):  # type: ignore[no-untyped-def]
        events.append((event_type, kw))

    def fake_send_task(name, args=None, **kw):  # type: ignore[no-untyped-def]
        enqueued.append((name, args))

    monkeypatch.setattr(detect_mod, "publish", fake_publish)
    monkeypatch.setattr(detect_mod.celery_app, "send_task", fake_send_task)
    monkeypatch.setattr(vd_ml, "load_yolo", lambda path: object())

    def set_boxes(boxes_by_index: dict[int, list[Box]]) -> None:
        def fake_predict(model, paths, conf):  # type: ignore[no-untyped-def]
            return [boxes_by_index.get(int(p.stem.split("_")[1]), []) for p in paths]

        monkeypatch.setattr(vd_ml, "predict_batch", fake_predict)

    return SimpleNamespace(events=events, enqueued=enqueued, set_boxes=set_boxes)


async def test_detect_persists_and_completes(session, frames_dir, capture_io):  # type: ignore[no-untyped-def]
    person_id = await session.scalar(select(Class.id).where(Class.name == "person"))
    clip, frames = await _seed(session, frames_dir, n_frames=2)

    capture_io.set_boxes({
        0: [
            Box(class_index=0, score=0.9, bbox={"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.4}),
            Box(class_index=5, score=0.8, bbox={"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2}),
        ],  # class 5 (bus) is not a builtin -> dropped
        1: [],  # no objects -> kept on disk so the user can add a box manually
    })

    n = await _detect_frame_batch_async([str(f.id) for f in frames])
    assert n == 2

    # Exactly one detection (the bus box was dropped), with an audit row.
    dets = (await session.scalars(select(DetectionModel))).all()
    assert len(dets) == 1
    det = dets[0]
    assert det.class_id == person_id
    assert det.predicted_class_id == person_id
    assert det.source == "model"
    assert det.confidence_class == pytest.approx(0.9)

    audits = (await session.scalars(select(DetectionAudit))).all()
    assert len(audits) == 1
    assert audits[0].reason == "initial_prediction"
    assert audits[0].to_class_id == person_id

    # Both frames stay kept=True — object-free frames are retained so the user
    # can manually add detections YOLO missed. Dedup is the only path that
    # flips kept=False + schedules pruning.
    await session.refresh(frames[0])
    await session.refresh(frames[1])
    assert frames[0].detect_status == "done" and frames[0].kept is True
    assert frames[1].detect_status == "done" and frames[1].kept is True
    assert not any(name == "vd.prune_frame" for name, _ in capture_io.enqueued)

    # All frames detected -> clip done, completion broadcast.
    await session.refresh(clip)
    assert clip.status == "done"
    assert ("clip.done", {"clip_id": str(clip.id)}) in capture_io.events


async def test_detect_raises_when_frame_jpeg_missing(session, frames_dir, capture_io):  # type: ignore[no-untyped-def]
    """A pending frame with no file on disk is a fault, not an empty frame."""
    _, frames = await _seed(session, frames_dir, n_frames=2)
    capture_io.set_boxes({})
    (frames_dir / frames[0].path).unlink()  # simulate a lost/misplaced frame file

    with pytest.raises(RuntimeError, match="JPEG missing"):
        await _detect_frame_batch_async([str(f.id) for f in frames])


async def test_detect_is_idempotent(session, frames_dir, capture_io):  # type: ignore[no-untyped-def]
    _, frames = await _seed(session, frames_dir, n_frames=1)
    capture_io.set_boxes(
        {0: [Box(class_index=0, score=0.9, bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2})]}
    )
    ids = [str(f.id) for f in frames]

    assert await _detect_frame_batch_async(ids) == 1
    # Re-running skips frames already marked done — no duplicate detections.
    assert await _detect_frame_batch_async(ids) == 0

    dets = (await session.scalars(select(DetectionModel))).all()
    assert len(dets) == 1

"""Tests for `vd.predict_user_detection` (YOLO predict for a hand-drawn box).

The YOLO model is faked (`load_yolo` / `predict_batch` patched) so the test
is deterministic; the DB, audit ledger, and embed-chain dispatch all run for
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
    Subclass,
)
from vd_ml import Box
from worker.tasks import predict_user_detection as predict_mod
from worker.tasks.predict_user_detection import _predict_user_detection_async


async def _seed_user_detection(  # type: ignore[no-untyped-def]
    session,
    frames_dir,
    *,
    bbox=None,
    class_id=None,
):
    bbox = bbox or {"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.3}
    clip = Clip(
        filename="t.mp4", original_path="/in/t.mp4",
        sha256=uuid.uuid4().hex, size_bytes=1, status="done",
    )
    session.add(clip)
    await session.flush()
    frame = Frame(
        clip_id=clip.id, frame_index=0, timestamp_sec=0.0,
        path=f"{clip.id}/frame_000000.jpg", width=640, height=480,
        kept=True, detect_status="done",
    )
    session.add(frame)
    session.add(
        ModelVersion(kind="yolo", name="test-yolo", weights_path="/models/test.pt",
                     is_active=True)
    )
    await session.flush()
    detection = DetectionModel(
        frame_id=frame.id, class_id=class_id, bbox=bbox, source="user",
        reviewed=True,
    )
    session.add(detection)
    await session.commit()
    fp = frames_dir / frame.path
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_bytes(b"\xff\xd8\xff")  # content irrelevant — predict_batch is faked
    return clip, frame, detection


@pytest.fixture
def capture_io(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    events: list = []
    enqueued: list = []

    async def fake_publish(event_type, **kw):  # type: ignore[no-untyped-def]
        events.append((event_type, kw))

    def fake_send_task(name, args=None, **kw):  # type: ignore[no-untyped-def]
        enqueued.append((name, args))

    monkeypatch.setattr(predict_mod, "publish", fake_publish)
    monkeypatch.setattr(predict_mod.celery_app, "send_task", fake_send_task)
    monkeypatch.setattr(vd_ml, "load_yolo", lambda path: object())

    def set_boxes(boxes: list[Box]) -> None:
        def fake_predict(model, paths, conf):  # type: ignore[no-untyped-def]
            return [boxes]

        monkeypatch.setattr(vd_ml, "predict_batch", fake_predict)

    return SimpleNamespace(events=events, enqueued=enqueued, set_boxes=set_boxes)


async def test_predict_auto_assigns_when_class_was_null(  # type: ignore[no-untyped-def]
    session, frames_dir, capture_io
):
    """User drew a box without picking a class → predict fills both
    `predicted_class_id` and `class_id`, audit logged, embed chained."""
    person = (
        await session.scalars(select(Class).where(Class.name == "person"))
    ).one()
    person_id = person.id
    # Make person subclassed so embed_object would be candidate too (it
    # shouldn't fire — person goes through recognize_face).
    session.add(Subclass(class_id=person_id, name="alice", is_active=True))
    await session.commit()

    _, frame, det = await _seed_user_detection(session, frames_dir)
    capture_io.set_boxes(
        [
            # Overlaps the user's bbox ~perfectly (same coords). The COCO index
            # for person is fetched at runtime: another test (finetune) can
            # remap indices and `classes` is not truncated between tests.
            Box(class_index=int(person.yolo_class_index), score=0.91,
                bbox={"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.3}),
        ]
    )

    ok = await _predict_user_detection_async(str(det.id))
    assert ok is True

    await session.refresh(det)
    assert det.predicted_class_id == person_id
    assert det.class_id == person_id  # auto-assigned
    assert det.confidence_class == pytest.approx(0.91)

    audits = (await session.scalars(select(DetectionAudit))).all()
    assert len(audits) == 1
    assert audits[0].reason == "initial_prediction"
    assert audits[0].to_class_id == person_id

    # person class → recognize_face, never embed_object
    names = [name for name, _ in capture_io.enqueued]
    assert names == ["vd.recognize_face"]
    assert ("frame.updated", {"clip_id": str(frame.clip_id), "frame_id": str(frame.id)}) \
        in capture_io.events


async def test_predict_leaves_user_chosen_class_alone(  # type: ignore[no-untyped-def]
    session, frames_dir, capture_io
):
    """User already picked a class → only predicted_class_id updates;
    class_id stays as the user's choice and no embed chain re-fires."""
    person = (
        await session.scalars(select(Class).where(Class.name == "person"))
    ).one()
    car_id = await session.scalar(select(Class.id).where(Class.name == "car"))
    assert person.id and car_id

    _, _, det = await _seed_user_detection(session, frames_dir, class_id=car_id)
    capture_io.set_boxes(
        [Box(class_index=int(person.yolo_class_index), score=0.9,
             bbox={"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.3})]
    )

    assert await _predict_user_detection_async(str(det.id)) is True

    await session.refresh(det)
    assert det.predicted_class_id == person.id  # YOLO's guess
    assert det.class_id == car_id  # user's choice wins
    # No embed chain when we didn't auto-assign — user already triggers
    # embedding through promote-example when they want it.
    assert capture_io.enqueued == []


async def test_predict_no_match_clears_prediction(  # type: ignore[no-untyped-def]
    session, frames_dir, capture_io
):
    """YOLO sees nothing above IoU 0.3 → prediction stays null, audit row
    still recorded so /metrics knows we tried."""
    person_index = await session.scalar(
        select(Class.yolo_class_index).where(Class.name == "person")
    )
    _, _, det = await _seed_user_detection(session, frames_dir)
    capture_io.set_boxes(
        [
            # Far corner — no overlap with the user's {0.1,0.1,0.3,0.3} bbox.
            Box(class_index=int(person_index), score=0.9,
                bbox={"x": 0.7, "y": 0.7, "w": 0.2, "h": 0.2}),
        ]
    )

    assert await _predict_user_detection_async(str(det.id)) is True

    await session.refresh(det)
    assert det.predicted_class_id is None
    assert det.class_id is None
    audits = (await session.scalars(select(DetectionAudit))).all()
    assert len(audits) == 1
    assert audits[0].to_class_id is None
    assert capture_io.enqueued == []


async def test_predict_skips_deleted_detection(  # type: ignore[no-untyped-def]
    session, frames_dir, capture_io
):
    from datetime import UTC, datetime

    _, _, det = await _seed_user_detection(session, frames_dir)
    det.deleted_at = datetime.now(UTC)
    await session.commit()
    capture_io.set_boxes([])

    assert await _predict_user_detection_async(str(det.id)) is False
    assert capture_io.enqueued == []
    assert capture_io.events == []


async def test_predict_skips_model_source_detection(  # type: ignore[no-untyped-def]
    session, frames_dir, capture_io
):
    """The predict endpoint is only meaningful for user-drawn boxes; a model
    detection already has its prediction and re-running would just churn audits."""
    person_index = await session.scalar(
        select(Class.yolo_class_index).where(Class.name == "person")
    )
    _, _, det = await _seed_user_detection(session, frames_dir)
    det.source = "model"
    await session.commit()
    capture_io.set_boxes(
        [Box(class_index=int(person_index), score=0.9,
             bbox={"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.3})]
    )

    assert await _predict_user_detection_async(str(det.id)) is False

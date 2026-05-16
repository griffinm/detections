"""Tests for the on-the-fly metrics endpoints."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from vd_db.models import Class, Clip, DetectionAudit, DetectionModel, Frame, ModelVersion


async def _seed(session):  # type: ignore[no-untyped-def]
    """8 reviewed person detections, all confidence 0.9: 6 predicted person
    (correct), 2 predicted car (wrong). Returns (model_version_id, person, car)."""
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    car = await session.scalar(select(Class.id).where(Class.name == "car"))
    model = ModelVersion(kind="yolo", name="m", weights_path="/m.pt")
    session.add(model)
    clip = Clip(
        filename="t.mp4", original_path="/in/t.mp4",
        sha256=uuid.uuid4().hex, size_bytes=1, status="done",
    )
    session.add(clip)
    await session.flush()
    frame = Frame(
        clip_id=clip.id, frame_index=0, timestamp_sec=0.0,
        path="f.jpg", width=10, height=10, kept=True, detect_status="done",
    )
    session.add(frame)
    await session.flush()
    now = datetime.now(UTC)
    for i in range(8):
        session.add(
            DetectionModel(
                frame_id=frame.id, class_id=person,
                predicted_class_id=person if i < 6 else car,
                bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, source="model",
                model_version_id=model.id, confidence_class=0.9,
                reviewed=True, reviewed_at=now,
            )
        )
    await session.commit()
    return str(model.id), str(person), str(car)


async def test_accuracy_time_series(client, session):  # type: ignore[no-untyped-def]
    model_id, _person, _car = await _seed(session)
    resp = await client.get("/api/metrics/accuracy?bucket=day")
    assert resp.status_code == 200
    point = next(p for p in resp.json() if p["model_version_id"] == model_id)
    assert point["n_reviewed"] == 8
    assert point["class_top1"] == pytest.approx(0.75)
    assert point["mean_confidence"] == pytest.approx(0.9, abs=1e-5)


async def test_accuracy_rejects_bad_bucket(client):  # type: ignore[no-untyped-def]
    assert (await client.get("/api/metrics/accuracy?bucket=year")).status_code == 422


async def test_per_class_precision_and_recall(client, session):  # type: ignore[no-untyped-def]
    _model, person, car = await _seed(session)
    by_id = {m["class_id"]: m for m in (await client.get("/api/metrics/per-class")).json()}
    assert by_id[person]["precision"] == pytest.approx(1.0)
    assert by_id[person]["recall"] == pytest.approx(0.75)
    assert by_id[person]["n_actual"] == 8
    assert by_id[car]["precision"] == pytest.approx(0.0)
    assert by_id[car]["n_predicted"] == 2


async def test_calibration_bins_and_ece(client, session):  # type: ignore[no-untyped-def]
    await _seed(session)
    body = (await client.get("/api/metrics/calibration")).json()
    assert len(body["bins"]) == 1
    only = body["bins"][0]
    assert only["count"] == 8
    assert only["mean_confidence"] == pytest.approx(0.9, abs=1e-5)
    assert only["empirical_accuracy"] == pytest.approx(0.75)
    # ECE = |0.75 - 0.9| * 8/8
    assert body["ece"] == pytest.approx(0.15, abs=1e-4)


async def test_summary_counts(client, session):  # type: ignore[no-untyped-def]
    await _seed(session)
    body = (await client.get("/api/metrics/summary")).json()
    assert body["detections"] == 8
    assert body["reviewed"] == 8
    assert body["pending_review"] == 0
    assert body["clips"] >= 1
    assert body["last7d_class_accuracy"] == pytest.approx(0.75)


async def test_changes_lists_recent_reassignments(client, session):  # type: ignore[no-untyped-def]
    _model, person, car = await _seed(session)
    detection = await session.scalar(select(DetectionModel).limit(1))
    session.add(
        DetectionAudit(
            detection_id=detection.id, reason="user_reassign",
            from_class_id=uuid.UUID(car), to_class_id=uuid.UUID(person),
        )
    )
    await session.commit()

    items = (await client.get("/api/metrics/changes")).json()
    assert len(items) == 1
    assert items[0]["reason"] == "user_reassign"
    assert items[0]["from_class"] == "car"
    assert items[0]["to_class"] == "person"

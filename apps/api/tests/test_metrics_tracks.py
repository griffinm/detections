"""Smoke test for `GET /api/metrics/tracks`."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from vd_db.models import Class, Clip, ModelVersion, Subclass, Track


async def test_metrics_tracks_returns_reviewed_only(client, session):  # type: ignore[no-untyped-def]
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    sub = Subclass(class_id=person, name="Mallory")
    session.add(sub)
    clip = Clip(
        filename="t.mp4", original_path="/in/t.mp4",
        sha256=uuid.uuid4().hex, size_bytes=1, status="done",
    )
    session.add(clip)
    await session.flush()
    model = ModelVersion(
        kind="yolo", name="yolo-test", weights_path="/m.pt", is_active=True
    )
    session.add(model)
    await session.flush()

    # Two reviewed tracks (one with matching prediction, one mismatched) and
    # one unreviewed track that should be ignored.
    reviewed_correct = Track(
        clip_id=clip.id, class_id=person, subclass_id=sub.id,
        predicted_class_id=person, predicted_subclass_id=sub.id,
        source="tracker", first_frame_index=0, last_frame_index=2,
        n_detections=3, confidence_class=0.95, confidence_subclass=0.9,
        model_version_id=model.id, reviewed=True, reviewed_at=datetime.now(UTC),
    )
    reviewed_wrong = Track(
        clip_id=clip.id, class_id=person, subclass_id=None,
        predicted_class_id=person, predicted_subclass_id=sub.id,
        source="tracker", first_frame_index=3, last_frame_index=4,
        n_detections=2, confidence_class=0.8, confidence_subclass=0.6,
        model_version_id=model.id, reviewed=True, reviewed_at=datetime.now(UTC),
    )
    unreviewed = Track(
        clip_id=clip.id, class_id=person, predicted_class_id=person,
        source="tracker", first_frame_index=5, last_frame_index=6,
        n_detections=2, confidence_class=0.7, model_version_id=model.id,
        reviewed=False,
    )
    session.add_all([reviewed_correct, reviewed_wrong, unreviewed])
    await session.commit()

    resp = await client.get("/api/metrics/tracks?bucket=day")
    assert resp.status_code == 200
    points = resp.json()
    assert len(points) == 1
    point = points[0]
    assert point["n_reviewed"] == 2  # unreviewed track excluded
    assert point["class_top1"] == 1.0  # both reviewed have correct class
    # One reviewed track has matching sub-class, one doesn't → 0.5.
    assert point["subclass_top1"] == 0.5

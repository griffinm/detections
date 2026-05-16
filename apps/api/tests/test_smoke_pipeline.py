"""API smoke test — walks the accuracy loop: ingested clip → label → metric.

Drives the same endpoints the labeling UI uses (PATCH a detection, review the
frame) and asserts the on-the-fly metrics move accordingly. No browser, no
worker, no GPU — the clip is seeded as already-detected.
"""

import uuid

import pytest
from sqlalchemy import select

from vd_db.models import Class, Clip, DetectionModel, Frame


async def test_label_to_metric_flow(client, session):  # type: ignore[no-untyped-def]
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    car = await session.scalar(select(Class.id).where(Class.name == "car"))

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
    detections = []
    for _ in range(4):
        det = DetectionModel(
            frame_id=frame.id, class_id=person, predicted_class_id=person,
            bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, source="model",
            confidence_class=0.8, reviewed=False,
        )
        session.add(det)
        detections.append(det)
    await session.commit()

    # Detection done, nothing reviewed yet.
    summary = (await client.get("/api/metrics/summary")).json()
    assert summary["detections"] == 4
    assert summary["reviewed"] == 0
    assert summary["pending_review"] == 4

    # Correct one prediction (person → car), then review the whole frame.
    patch = await client.patch(
        f"/api/detections/{detections[0].id}", json={"class_id": str(car)}
    )
    assert patch.status_code == 200
    assert (await client.post(f"/api/frames/{frame.id}/review")).status_code == 200

    # Metrics now reflect the review: 4 reviewed, 3 of 4 predictions correct.
    summary = (await client.get("/api/metrics/summary")).json()
    assert summary["reviewed"] == 4
    assert summary["pending_review"] == 0
    assert summary["last7d_class_accuracy"] == pytest.approx(0.75)

    accuracy = (await client.get("/api/metrics/accuracy?bucket=day")).json()
    assert len(accuracy) == 1
    assert accuracy[0]["n_reviewed"] == 4
    assert accuracy[0]["class_top1"] == pytest.approx(0.75)

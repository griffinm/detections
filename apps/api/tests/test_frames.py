"""Tests for the frame-detail endpoint."""

import uuid

from sqlalchemy import func, select

from vd_db.models import Clip, DetectionModel, Frame


async def _seed_frame(session):  # type: ignore[no-untyped-def]
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
    await session.flush()
    for i in range(2):
        session.add(
            DetectionModel(
                frame_id=frame.id, source="model",
                bbox={"x": 0.1 * i, "y": 0.1, "w": 0.3, "h": 0.4},
                confidence_class=0.8,
            )
        )
    await session.commit()
    return frame


async def test_get_frame_includes_detections(client, session):  # type: ignore[no-untyped-def]
    frame = await _seed_frame(session)

    resp = await client.get(f"/api/frames/{frame.id}")
    assert resp.status_code == 200

    body = resp.json()
    assert body["id"] == str(frame.id)
    assert body["image_url"] == f"/files/frames/{frame.path}"
    assert body["detect_status"] == "done"
    assert len(body["detections"]) == 2
    assert body["detections"][0]["bbox"]["w"] == 0.3
    assert body["detections"][0]["source"] == "model"


async def test_get_frame_missing_returns_404(client):  # type: ignore[no-untyped-def]
    resp = await client.get(f"/api/frames/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_delete_frame_cascades_detections(client, session):  # type: ignore[no-untyped-def]
    frame = await _seed_frame(session)

    resp = await client.delete(f"/api/frames/{frame.id}")
    assert resp.status_code == 204

    session.expunge_all()  # drop identity-map cache so the get re-queries
    assert await session.get(Frame, frame.id) is None
    remaining = await session.scalar(
        select(func.count())
        .select_from(DetectionModel)
        .where(DetectionModel.frame_id == frame.id)
    )
    assert remaining == 0


async def test_delete_missing_frame_returns_404(client):  # type: ignore[no-untyped-def]
    resp = await client.delete(f"/api/frames/{uuid.uuid4()}")
    assert resp.status_code == 404

"""Tests for the review-queue endpoint."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from vd_db.models import Class, Clip, DetectionModel, Frame


def _frame(clip_id, index, **kw):  # type: ignore[no-untyped-def]
    return Frame(
        clip_id=clip_id, frame_index=index, timestamp_sec=float(index),
        path=f"{clip_id}/frame_{index:06d}.jpg", width=640, height=480,
        kept=True, detect_status="done", **kw,
    )


def _detection(frame_id, class_id, *, conf=0.5, reviewed=False):  # type: ignore[no-untyped-def]
    return DetectionModel(
        frame_id=frame_id, class_id=class_id, predicted_class_id=class_id,
        bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, source="model",
        confidence_class=conf, reviewed=reviewed,
    )


async def test_queue_orders_lowconf_and_skips_reviewed(client, session):  # type: ignore[no-untyped-def]
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    clip = Clip(
        filename="t.mp4", original_path="/in/t.mp4",
        sha256=uuid.uuid4().hex, size_bytes=1, status="done",
    )
    session.add(clip)
    await session.flush()

    # frame 0: unreviewed conf 0.9 — frame 1: unreviewed conf 0.3 — frame 2: reviewed
    specs = [(0, 0.9, False), (1, 0.3, False), (2, 0.5, True)]
    for index, conf, reviewed in specs:
        frame = Frame(
            clip_id=clip.id, frame_index=index, timestamp_sec=float(index),
            path=f"{clip.id}/frame_{index:06d}.jpg", width=640, height=480,
            kept=True, detect_status="done",
        )
        session.add(frame)
        await session.flush()
        session.add(
            DetectionModel(
                frame_id=frame.id, class_id=person, predicted_class_id=person,
                bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, source="model",
                confidence_class=conf, reviewed=reviewed,
            )
        )
    await session.commit()

    resp = await client.get("/api/labeling/queue?strategy=lowconf")
    assert resp.status_code == 200
    items = resp.json()

    # frame 2 fully reviewed -> absent; lowest confidence first.
    assert [i["frame_index"] for i in items] == [1, 0]
    assert items[0]["min_confidence"] == 0.3
    assert items[0]["unreviewed_count"] == 1


async def test_queue_rejects_unknown_strategy(client):  # type: ignore[no-untyped-def]
    resp = await client.get("/api/labeling/queue?strategy=bogus")
    assert resp.status_code == 400


async def test_queue_unreviewed_orders_newest_first(client, session):  # type: ignore[no-untyped-def]
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    clip = Clip(
        filename="t.mp4", original_path="/in/t.mp4",
        sha256=uuid.uuid4().hex, size_bytes=1, status="done",
    )
    session.add(clip)
    await session.flush()

    now = datetime.now(UTC)
    for index, age_min in [(0, 30), (1, 10), (2, 20)]:
        frame = _frame(clip.id, index, created_at=now - timedelta(minutes=age_min))
        session.add(frame)
        await session.flush()
        session.add(_detection(frame.id, person))
    await session.commit()

    items = (await client.get("/api/labeling/queue?strategy=unreviewed")).json()
    # newest created_at first: frame 1 (10m) > frame 2 (20m) > frame 0 (30m)
    assert [i["frame_index"] for i in items] == [1, 2, 0]


async def test_queue_class_filter(client, session):  # type: ignore[no-untyped-def]
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    car = await session.scalar(select(Class.id).where(Class.name == "car"))
    clip = Clip(
        filename="t.mp4", original_path="/in/t.mp4",
        sha256=uuid.uuid4().hex, size_bytes=1, status="done",
    )
    session.add(clip)
    await session.flush()

    for index, cls in [(0, person), (1, car)]:
        frame = _frame(clip.id, index)
        session.add(frame)
        await session.flush()
        session.add(_detection(frame.id, cls))
    await session.commit()

    items = (await client.get(f"/api/labeling/queue?class_id={person}")).json()
    assert [i["frame_index"] for i in items] == [0]
    assert items[0]["unreviewed_count"] == 1

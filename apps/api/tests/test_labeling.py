"""Tests for the review-queue, predicted-groups, and bulk-review endpoints."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from vd_db.models import Class, Clip, DetectionAudit, DetectionModel, Frame, Subclass


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


# ---------------------------------------------------------------------------
# Bulk-review + predicted-groups
# ---------------------------------------------------------------------------


async def _seed_clip(session, n_frames=1):  # type: ignore[no-untyped-def]
    clip = Clip(
        filename="t.mp4", original_path="/in/t.mp4",
        sha256=uuid.uuid4().hex, size_bytes=1, status="done",
    )
    session.add(clip)
    await session.flush()
    frames = []
    for i in range(n_frames):
        frame = Frame(
            clip_id=clip.id, frame_index=i, timestamp_sec=float(i),
            path=f"{clip.id}/frame_{i:06d}.jpg", width=640, height=480,
            kept=True, detect_status="done",
        )
        session.add(frame)
        frames.append(frame)
    await session.flush()
    return clip, frames


async def _audits(session, detection_id):  # type: ignore[no-untyped-def]
    return (
        await session.scalars(
            select(DetectionAudit)
            .where(DetectionAudit.detection_id == detection_id)
            .order_by(DetectionAudit.id)
        )
    ).all()


async def test_bulk_review_marks_reviewed_and_writes_audits(client, session):  # type: ignore[no-untyped-def]
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    _, frames = await _seed_clip(session, n_frames=3)
    dets = [_detection(f.id, person) for f in frames]
    for d in dets:
        session.add(d)
    await session.commit()

    resp = await client.post(
        "/api/labeling/bulk-review",
        json={"detection_ids": [str(d.id) for d in dets], "reviewed": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["updated"] == 3
    assert body["skipped"] == 0
    assert body["audits_written"] == 3
    # frame_ids dedup — three different frames here
    assert len(body["affected_frame_ids"]) == 3

    for d in dets:
        await session.refresh(d)
        assert d.reviewed is True
        assert d.reviewed_at is not None
        rows = await _audits(session, d.id)
        assert [a.reason for a in rows] == ["user_review"]


async def test_bulk_review_idempotent_when_already_reviewed(client, session):  # type: ignore[no-untyped-def]
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    _, frames = await _seed_clip(session, n_frames=2)
    dets = [_detection(f.id, person, reviewed=True) for f in frames]
    for d in dets:
        d.reviewed_at = datetime.now(UTC)
        session.add(d)
    await session.commit()

    resp = await client.post(
        "/api/labeling/bulk-review",
        json={"detection_ids": [str(d.id) for d in dets], "reviewed": True},
    )
    body = resp.json()
    assert body["updated"] == 0
    assert body["audits_written"] == 0
    for d in dets:
        assert await _audits(session, d.id) == []


async def test_bulk_review_reassign_subclass_writes_one_audit_per_change(  # type: ignore[no-untyped-def]
    client, session,
):
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    sub_a = Subclass(class_id=person, name="rex", color_hex="#aa0000", is_active=True)
    sub_b = Subclass(class_id=person, name="biscuit", color_hex="#00aa00", is_active=True)
    session.add_all([sub_a, sub_b])
    await session.flush()

    _, frames = await _seed_clip(session, n_frames=3)
    # First two already point at sub_a; third is unassigned.
    d1 = _detection(frames[0].id, person)
    d1.subclass_id = sub_a.id
    d2 = _detection(frames[1].id, person)
    d2.subclass_id = sub_a.id
    d3 = _detection(frames[2].id, person)
    session.add_all([d1, d2, d3])
    await session.commit()

    resp = await client.post(
        "/api/labeling/bulk-review",
        json={
            "detection_ids": [str(d1.id), str(d2.id), str(d3.id)],
            "subclass_id": str(sub_b.id),
            "reviewed": True,
        },
    )
    body = resp.json()
    # All three reassign (one audit each) AND all three review (one audit each)
    assert body["updated"] == 3
    assert body["audits_written"] == 6

    for d, prior in [(d1, sub_a.id), (d2, sub_a.id), (d3, None)]:
        rows = await _audits(session, d.id)
        assert [a.reason for a in rows] == ["user_reassign", "user_review"]
        assert rows[0].from_subclass_id == prior
        assert rows[0].to_subclass_id == sub_b.id


async def test_bulk_review_skips_subclass_with_mismatched_class(client, session):  # type: ignore[no-untyped-def]
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    car = await session.scalar(select(Class.id).where(Class.name == "car"))
    sub_person = Subclass(class_id=person, name="rex", color_hex="#aa0000", is_active=True)
    session.add(sub_person)
    await session.flush()

    _, frames = await _seed_clip(session, n_frames=2)
    d_person = _detection(frames[0].id, person)
    d_car = _detection(frames[1].id, car)
    session.add_all([d_person, d_car])
    await session.commit()

    resp = await client.post(
        "/api/labeling/bulk-review",
        json={
            "detection_ids": [str(d_person.id), str(d_car.id)],
            "subclass_id": str(sub_person.id),
        },
    )
    body = resp.json()
    # Only the person detection should be updated; the car one is skipped.
    assert body["updated"] == 1
    assert body["skipped"] == 1
    await session.refresh(d_person)
    await session.refresh(d_car)
    assert d_person.subclass_id == sub_person.id
    assert d_car.subclass_id is None


async def test_bulk_review_skips_soft_deleted_rows(client, session):  # type: ignore[no-untyped-def]
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    _, frames = await _seed_clip(session, n_frames=2)
    d_live = _detection(frames[0].id, person)
    d_dead = _detection(frames[1].id, person)
    d_dead.deleted_at = datetime.now(UTC)
    session.add_all([d_live, d_dead])
    await session.commit()

    resp = await client.post(
        "/api/labeling/bulk-review",
        json={"detection_ids": [str(d_live.id), str(d_dead.id)], "reviewed": True},
    )
    body = resp.json()
    assert body["updated"] == 1
    assert body["skipped"] == 1


async def test_bulk_review_requires_at_least_one_field(client, session):  # type: ignore[no-untyped-def]
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    _, frames = await _seed_clip(session, n_frames=1)
    d = _detection(frames[0].id, person)
    session.add(d)
    await session.commit()

    resp = await client.post(
        "/api/labeling/bulk-review",
        json={"detection_ids": [str(d.id)]},
    )
    assert resp.status_code == 422


async def test_bulk_review_409_when_class_and_subclass_disagree(client, session):  # type: ignore[no-untyped-def]
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    car = await session.scalar(select(Class.id).where(Class.name == "car"))
    sub_person = Subclass(class_id=person, name="rex", color_hex="#aa0000", is_active=True)
    session.add(sub_person)
    await session.flush()

    _, frames = await _seed_clip(session, n_frames=1)
    d = _detection(frames[0].id, person)
    session.add(d)
    await session.commit()

    resp = await client.post(
        "/api/labeling/bulk-review",
        json={
            "detection_ids": [str(d.id)],
            "class_id": str(car),
            "subclass_id": str(sub_person.id),
        },
    )
    assert resp.status_code == 409


async def test_predicted_groups_buckets_by_confidence(client, session):  # type: ignore[no-untyped-def]
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    sub = Subclass(class_id=person, name="rex", color_hex="#aa0000", is_active=True)
    session.add(sub)
    await session.flush()

    _, frames = await _seed_clip(session, n_frames=5)
    # confidences: two high (>=0.85), two med (>=0.7), one below default
    # `subclass_min_confidence` (0.55) — filtered out by the default.
    confidences = [0.95, 0.90, 0.75, 0.72, 0.40]
    for frame, conf in zip(frames, confidences, strict=True):
        det = _detection(frame.id, person)
        det.predicted_subclass_id = sub.id
        det.confidence_subclass = conf
        session.add(det)
    await session.commit()

    resp = await client.get("/api/labeling/predicted-groups")
    assert resp.status_code == 200
    groups = resp.json()
    # Two buckets surface (high, med); below-threshold row dropped.
    by_bucket = {g["confidence_bucket"]: g for g in groups}
    assert set(by_bucket) == {"high", "med"}
    assert by_bucket["high"]["count"] == 2
    assert by_bucket["med"]["count"] == 2
    assert by_bucket["high"]["predicted_subclass_name"] == "rex"
    # 'high' must come before 'med' in the response.
    assert groups[0]["confidence_bucket"] == "high"


async def test_predicted_groups_excludes_reviewed(client, session):  # type: ignore[no-untyped-def]
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    sub = Subclass(class_id=person, name="rex", color_hex="#aa0000", is_active=True)
    session.add(sub)
    await session.flush()

    _, frames = await _seed_clip(session, n_frames=2)
    seen = _detection(frames[0].id, person, reviewed=True)
    seen.predicted_subclass_id = sub.id
    seen.confidence_subclass = 0.9
    unseen = _detection(frames[1].id, person)
    unseen.predicted_subclass_id = sub.id
    unseen.confidence_subclass = 0.9
    session.add_all([seen, unseen])
    await session.commit()

    groups = (await client.get("/api/labeling/predicted-groups")).json()
    assert len(groups) == 1
    assert groups[0]["count"] == 1
    assert groups[0]["sample_detection_ids"] == [str(unseen.id)]

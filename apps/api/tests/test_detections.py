"""Tests for detection CRUD and the audit ledger."""

import uuid

from sqlalchemy import select

from vd_db.models import Class, Clip, DetectionAudit, DetectionModel, Frame


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
    return clip, frame


async def _class_id(session, name):  # type: ignore[no-untyped-def]
    return await session.scalar(select(Class.id).where(Class.name == name))


async def _audits(session, detection_id):  # type: ignore[no-untyped-def]
    return (
        await session.scalars(
            select(DetectionAudit).where(DetectionAudit.detection_id == detection_id)
        )
    ).all()


async def test_create_user_detection_writes_audit(client, session):  # type: ignore[no-untyped-def]
    _, frame = await _seed_frame(session)
    person = await _class_id(session, "person")
    await session.commit()

    resp = await client.post(
        "/api/detections",
        json={
            "frame_id": str(frame.id),
            "bbox": {"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.4},
            "class_id": str(person),
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["source"] == "user"
    assert body["reviewed"] is True

    audits = await _audits(session, uuid.UUID(body["id"]))
    assert [a.reason for a in audits] == ["user_reassign"]
    assert audits[0].to_class_id == person


async def test_patch_reassign_and_review_audits(client, session):  # type: ignore[no-untyped-def]
    _, frame = await _seed_frame(session)
    person = await _class_id(session, "person")
    car = await _class_id(session, "car")
    det = DetectionModel(
        frame_id=frame.id, class_id=person, predicted_class_id=person,
        bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, source="model",
        confidence_class=0.5,
    )
    session.add(det)
    await session.commit()

    reclass = await client.patch(f"/api/detections/{det.id}", json={"class_id": str(car)})
    assert reclass.status_code == 200
    assert reclass.json()["class_id"] == str(car)

    review = await client.patch(f"/api/detections/{det.id}", json={"reviewed": True})
    assert review.json()["reviewed"] is True

    audits = await _audits(session, det.id)
    assert [a.reason for a in audits] == ["user_reassign", "user_review"]
    assert audits[0].from_class_id == person
    assert audits[0].to_class_id == car


async def test_patch_bbox_only_writes_no_audit(client, session):  # type: ignore[no-untyped-def]
    _, frame = await _seed_frame(session)
    person = await _class_id(session, "person")
    det = DetectionModel(
        frame_id=frame.id, class_id=person, predicted_class_id=person,
        bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, source="model",
        confidence_class=0.5,
    )
    session.add(det)
    await session.commit()

    resp = await client.patch(
        f"/api/detections/{det.id}",
        json={"bbox": {"x": 0.2, "y": 0.2, "w": 0.3, "h": 0.3}},
    )
    assert resp.status_code == 200
    assert await _audits(session, det.id) == []


async def test_delete_is_soft_audited_and_hidden(client, session):  # type: ignore[no-untyped-def]
    _, frame = await _seed_frame(session)
    person = await _class_id(session, "person")
    det = DetectionModel(
        frame_id=frame.id, class_id=person, predicted_class_id=person,
        bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, source="model",
        confidence_class=0.5,
    )
    session.add(det)
    await session.commit()

    assert (await client.delete(f"/api/detections/{det.id}")).status_code == 204

    # Row + audit survive; the detection drops out of the frame view.
    assert det.deleted_at is not None
    audits = await _audits(session, det.id)
    assert [a.reason for a in audits] == ["user_delete"]
    frame_resp = await client.get(f"/api/frames/{frame.id}")
    assert frame_resp.json()["detections"] == []

    # Restore brings it back.
    restored = await client.post(f"/api/detections/{det.id}/restore")
    assert restored.status_code == 200
    assert det.deleted_at is None
    frame_resp = await client.get(f"/api/frames/{frame.id}")
    assert len(frame_resp.json()["detections"]) == 1

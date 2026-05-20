"""Tests for the classes endpoint."""

import uuid

from sqlalchemy import select

from vd_db.models import Class, Clip, DetectionModel, Frame


async def _class_id(session, name):  # type: ignore[no-untyped-def]
    return await session.scalar(select(Class.id).where(Class.name == name))


async def _seed_class_detection(session, *, class_id, subclass_id=None):  # type: ignore[no-untyped-def]
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
    det = DetectionModel(
        frame_id=frame.id, class_id=class_id, subclass_id=subclass_id,
        bbox={"x": 0.2, "y": 0.2, "w": 0.3, "h": 0.3}, source="model",
    )
    session.add(det)
    await session.commit()
    return det


async def test_list_classes_returns_seeded_builtins(client):  # type: ignore[no-untyped-def]
    resp = await client.get("/api/classes")
    assert resp.status_code == 200

    by_name = {c["name"]: c for c in resp.json()}
    assert set(by_name) == {"person", "car", "dog", "bear"}
    assert by_name["person"]["yolo_class_index"] == 0
    assert by_name["dog"]["yolo_class_index"] == 16
    assert by_name["car"]["source"] == "builtin"


async def test_create_update_delete_class(client):  # type: ignore[no-untyped-def]
    created = await client.post(
        "/api/classes", json={"name": "deer", "color_hex": "#22c55e"}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["source"] == "custom"
    assert body["is_active"] is True
    class_id = body["id"]

    # Duplicate name is rejected.
    dup = await client.post("/api/classes", json={"name": "deer"})
    assert dup.status_code == 409

    patched = await client.patch(
        f"/api/classes/{class_id}", json={"color_hex": "#000000"}
    )
    assert patched.status_code == 200
    assert patched.json()["color_hex"] == "#000000"

    # Delete is a soft deactivate.
    assert (await client.delete(f"/api/classes/{class_id}")).status_code == 204
    listing = await client.get("/api/classes")
    deer = next(c for c in listing.json() if c["id"] == class_id)
    assert deer["is_active"] is False


async def test_class_detections_aggregates_across_subclasses(client, session):  # type: ignore[no-untyped-def]
    person = await _class_id(session, "person")
    sub_a = (
        await client.post(f"/api/classes/{person}/subclasses", json={"name": "Alice"})
    ).json()["id"]
    sub_b = (
        await client.post(f"/api/classes/{person}/subclasses", json={"name": "Bob"})
    ).json()["id"]

    det_a = await _seed_class_detection(session, class_id=person, subclass_id=uuid.UUID(sub_a))
    det_b = await _seed_class_detection(session, class_id=person, subclass_id=uuid.UUID(sub_b))
    det_unassigned = await _seed_class_detection(session, class_id=person, subclass_id=None)

    resp = await client.get(f"/api/classes/{person}/detections")
    assert resp.status_code == 200
    ids = {d["id"] for d in resp.json()}
    assert ids == {str(det_a.id), str(det_b.id), str(det_unassigned.id)}


async def test_class_examples_aggregates_active_subclasses_only(client, session):  # type: ignore[no-untyped-def]
    person = await _class_id(session, "person")
    sub_a_id = (
        await client.post(f"/api/classes/{person}/subclasses", json={"name": "Alice"})
    ).json()["id"]
    sub_b_id = (
        await client.post(f"/api/classes/{person}/subclasses", json={"name": "Bob"})
    ).json()["id"]
    det_a = await _seed_class_detection(session, class_id=person, subclass_id=uuid.UUID(sub_a_id))
    det_b = await _seed_class_detection(session, class_id=person, subclass_id=uuid.UUID(sub_b_id))
    await client.post(
        f"/api/subclasses/{sub_a_id}/examples", json={"detection_id": str(det_a.id)}
    )
    await client.post(
        f"/api/subclasses/{sub_b_id}/examples", json={"detection_id": str(det_b.id)}
    )

    resp = await client.get(f"/api/classes/{person}/examples")
    assert resp.status_code == 200
    body = resp.json()
    assert {ex["subclass_id"] for ex in body} == {sub_a_id, sub_b_id}

    # Deactivating a sub-class hides its examples from the class roll-up.
    await client.delete(f"/api/subclasses/{sub_b_id}")
    after = (await client.get(f"/api/classes/{person}/examples")).json()
    assert {ex["subclass_id"] for ex in after} == {sub_a_id}


async def test_class_detections_404(client):  # type: ignore[no-untyped-def]
    missing = uuid.uuid4()
    assert (await client.get(f"/api/classes/{missing}/detections")).status_code == 404
    assert (await client.get(f"/api/classes/{missing}/examples")).status_code == 404

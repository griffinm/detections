"""Tests for the classes endpoint."""

import uuid

from sqlalchemy import select

from vd_db.models import Class, Clip, DetectionModel, Frame, ModelVersion


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


async def test_catalog_falls_back_to_coco80_without_active_yolo(client):  # type: ignore[no-untyped-def]
    """Fresh install — no ModelVersion registered yet, but the picker still
    works against the well-known COCO-80 list."""
    resp = await client.get("/api/classes/catalog")
    assert resp.status_code == 200
    by_name = {e["name"]: e for e in resp.json()}
    # COCO 80 names total.
    assert len(by_name) == 80
    assert by_name["person"]["yolo_class_index"] == 0
    assert by_name["dog"]["yolo_class_index"] == 16
    # `person` is one of the seeded builtins → in_use.
    assert by_name["person"]["in_use"] is True
    assert by_name["cat"]["in_use"] is False


async def test_catalog_unions_active_yolo_class_names_with_coco80(client, session):  # type: ignore[no-untyped-def]
    """A trimmed fine-tune doesn't hide the COCO-80 names from the picker.

    The active model's indices win for names it knows; COCO-only names appear
    with a null index so a stale COCO index can't disagree with whatever the
    fine-tune emits at that slot.
    """
    session.add(
        ModelVersion(
            kind="yolo", name="ft", weights_path="/m.pt",
            # A fine-tune with custom classes — index 2 = "bear", not COCO's "car".
            metrics={"class_names": {"0": "person", "1": "dog", "2": "bear"}},
            is_active=True,
        )
    )
    await session.commit()

    resp = await client.get("/api/classes/catalog")
    assert resp.status_code == 200
    by_name = {e["name"]: e for e in resp.json()}
    # All COCO-80 names plus the fine-tune's custom additions (bear is already
    # in COCO-80; only truly new names enlarge the set).
    assert len(by_name) >= 80
    # Active model's index wins where it knows the name.
    assert by_name["person"]["yolo_class_index"] == 0
    assert by_name["dog"]["yolo_class_index"] == 1
    assert by_name["bear"]["yolo_class_index"] == 2
    # COCO-only name (active model doesn't emit it) → null index.
    assert by_name["cat"]["yolo_class_index"] is None
    assert by_name["car"]["yolo_class_index"] is None
    # `person` is one of the seeded builtins → in_use.
    assert by_name["person"]["in_use"] is True
    assert by_name["cat"]["in_use"] is False


async def test_create_class_with_yolo_class_index(client):  # type: ignore[no-untyped-def]
    created = await client.post(
        "/api/classes", json={"name": "cat", "yolo_class_index": 15}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["yolo_class_index"] == 15
    assert body["source"] == "custom"


async def test_create_class_rejects_duplicate_yolo_class_index(client):  # type: ignore[no-untyped-def]
    # `person` is seeded with yolo_class_index=0 — a second class can't take it.
    resp = await client.post(
        "/api/classes", json={"name": "humanoid", "yolo_class_index": 0}
    )
    assert resp.status_code == 409

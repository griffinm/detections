"""Tests for sub-class CRUD, the examples gallery, and promote-example."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from vd_db.models import Class, Clip, DetectionAudit, DetectionModel, Frame, SubclassExample


async def _class_id(session, name):  # type: ignore[no-untyped-def]
    return await session.scalar(select(Class.id).where(Class.name == name))


async def _seed_detection(session, class_name):  # type: ignore[no-untyped-def]
    """A committed frame + one model detection of `class_name`."""
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
    class_id = await _class_id(session, class_name)
    det = DetectionModel(
        frame_id=frame.id, class_id=class_id, predicted_class_id=class_id,
        bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, source="model",
        confidence_class=0.5,
    )
    session.add(det)
    await session.commit()
    return det


async def test_create_list_and_reject_duplicate_subclass(client, session):  # type: ignore[no-untyped-def]
    person = await _class_id(session, "person")

    created = await client.post(
        f"/api/classes/{person}/subclasses",
        json={"name": "Mallory", "color_hex": "#3b82f6"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Mallory"
    assert body["class_id"] == str(person)
    assert body["is_active"] is True

    dup = await client.post(
        f"/api/classes/{person}/subclasses", json={"name": "Mallory"}
    )
    assert dup.status_code == 409

    listing = await client.get(f"/api/classes/{person}/subclasses")
    assert [s["name"] for s in listing.json()] == ["Mallory"]


async def test_update_and_soft_delete_subclass(client, session):  # type: ignore[no-untyped-def]
    person = await _class_id(session, "person")
    sub_id = (
        await client.post(f"/api/classes/{person}/subclasses", json={"name": "Bob"})
    ).json()["id"]

    patched = await client.patch(
        f"/api/subclasses/{sub_id}", json={"color_hex": "#000000"}
    )
    assert patched.status_code == 200
    assert patched.json()["color_hex"] == "#000000"

    assert (await client.delete(f"/api/subclasses/{sub_id}")).status_code == 204
    fetched = await client.get(f"/api/subclasses/{sub_id}")
    assert fetched.json()["is_active"] is False


async def test_first_subclass_triggers_backfill(client, session, monkeypatch):  # type: ignore[no-untyped-def]
    enqueued: list = []
    monkeypatch.setattr(
        "api.routers.classes.enqueue",
        lambda name, *args, **kw: enqueued.append((name, args)),
    )
    person = await _class_id(session, "person")

    await client.post(f"/api/classes/{person}/subclasses", json={"name": "Mallory"})
    # The first active sub-class kicks off an embedding backfill.
    assert ("vd.backfill_embeddings", (str(person),)) in enqueued

    enqueued.clear()
    await client.post(f"/api/classes/{person}/subclasses", json={"name": "Bob"})
    # A second sub-class does not — the class is already eligible.
    assert enqueued == []


async def test_rescan_endpoint_enqueues_backfill(client, session, monkeypatch):  # type: ignore[no-untyped-def]
    enqueued: list = []
    monkeypatch.setattr(
        "api.routers.classes.enqueue",
        lambda name, *args, **kw: enqueued.append((name, args)),
    )
    person = await _class_id(session, "person")

    resp = await client.post(f"/api/classes/{person}/rescan-subclasses")
    assert resp.status_code == 202
    assert ("vd.backfill_embeddings", (str(person),)) in enqueued


async def test_example_add_list_delete(client, session):  # type: ignore[no-untyped-def]
    det = await _seed_detection(session, "person")
    person = det.class_id
    sub_id = (
        await client.post(f"/api/classes/{person}/subclasses", json={"name": "Mallory"})
    ).json()["id"]

    added = await client.post(
        f"/api/subclasses/{sub_id}/examples", json={"detection_id": str(det.id)}
    )
    assert added.status_code == 201
    example = added.json()
    assert example["detection_id"] == str(det.id)
    assert example["bbox"]["w"] == 0.2

    dup = await client.post(
        f"/api/subclasses/{sub_id}/examples", json={"detection_id": str(det.id)}
    )
    assert dup.status_code == 409

    listing = await client.get(f"/api/subclasses/{sub_id}/examples")
    assert listing.json()["total"] == 1
    assert len(listing.json()["items"]) == 1

    deleted = await client.delete(
        f"/api/subclasses/{sub_id}/examples/{example['id']}"
    )
    assert deleted.status_code == 204
    after = (await client.get(f"/api/subclasses/{sub_id}/examples")).json()
    assert after["items"] == []
    assert after["total"] == 0


async def test_promote_example_assigns_subclass_and_audits(client, session):  # type: ignore[no-untyped-def]
    det = await _seed_detection(session, "person")
    person = det.class_id
    sub_id = (
        await client.post(f"/api/classes/{person}/subclasses", json={"name": "Mallory"})
    ).json()["id"]

    resp = await client.post(
        f"/api/detections/{det.id}/promote-example", json={"subclass_id": sub_id}
    )
    assert resp.status_code == 200
    assert resp.json()["subclass_id"] == sub_id

    example = await session.scalar(
        select(SubclassExample).where(SubclassExample.detection_id == det.id)
    )
    assert example is not None and str(example.subclass_id) == sub_id

    audits = (
        await session.scalars(
            select(DetectionAudit).where(DetectionAudit.detection_id == det.id)
        )
    ).all()
    assert [a.reason for a in audits] == ["user_reassign"]
    assert str(audits[0].to_subclass_id) == sub_id


async def _seed_subclass_detection(  # type: ignore[no-untyped-def]
    session, *, class_id, subclass_id, reviewed, reviewed_at=None, deleted=False
):
    """A committed detection assigned to a sub-class with controllable state."""
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
        predicted_class_id=class_id, predicted_subclass_id=subclass_id,
        bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, source="model",
        confidence_class=0.7, confidence_subclass=0.6,
        reviewed=reviewed, reviewed_at=reviewed_at,
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    session.add(det)
    await session.commit()
    return det


async def test_subclass_detections_lists_filters_and_sorts(client, session):  # type: ignore[no-untyped-def]
    person = await _class_id(session, "person")
    sub_id = uuid.UUID(
        (
            await client.post(f"/api/classes/{person}/subclasses", json={"name": "Mallory"})
        ).json()["id"]
    )

    now = datetime.now(UTC)
    auto_old = await _seed_subclass_detection(
        session, class_id=person, subclass_id=sub_id, reviewed=False,
    )
    reviewed_new = await _seed_subclass_detection(
        session, class_id=person, subclass_id=sub_id, reviewed=True,
        reviewed_at=now - timedelta(minutes=1),
    )
    soft_deleted = await _seed_subclass_detection(
        session, class_id=person, subclass_id=sub_id, reviewed=True,
        reviewed_at=now, deleted=True,
    )

    all_ids = [
        d["id"]
        for d in (await client.get(f"/api/subclasses/{sub_id}/detections")).json()["items"]
    ]
    assert set(all_ids) == {str(auto_old.id), str(reviewed_new.id)}
    assert str(soft_deleted.id) not in all_ids  # soft-deleted excluded

    auto_only = (
        await client.get(f"/api/subclasses/{sub_id}/detections?include=auto")
    ).json()["items"]
    assert [d["id"] for d in auto_only] == [str(auto_old.id)]

    reviewed_only = (
        await client.get(f"/api/subclasses/{sub_id}/detections?include=reviewed")
    ).json()["items"]
    assert [d["id"] for d in reviewed_only] == [str(reviewed_new.id)]

    by_reviewed = (
        await client.get(
            f"/api/subclasses/{sub_id}/detections?sort=reviewed_desc"
        )
    ).json()["items"]
    # reviewed_at DESC NULLS LAST puts the reviewed one first.
    assert [d["id"] for d in by_reviewed] == [str(reviewed_new.id), str(auto_old.id)]

    item = reviewed_only[0]
    assert item["image_url"].startswith("/files/frames/")
    assert item["clip_id"]
    assert item["bbox"]["w"] == 0.2
    assert item["reviewed"] is True


async def test_subclass_detections_404(client):  # type: ignore[no-untyped-def]
    missing = uuid.uuid4()
    resp = await client.get(f"/api/subclasses/{missing}/detections")
    assert resp.status_code == 404


async def test_promote_example_rejects_cross_class_subclass(client, session):  # type: ignore[no-untyped-def]
    det = await _seed_detection(session, "person")
    car = await _class_id(session, "car")
    car_sub = (
        await client.post(f"/api/classes/{car}/subclasses", json={"name": "Sedan"})
    ).json()["id"]

    resp = await client.post(
        f"/api/detections/{det.id}/promote-example", json={"subclass_id": car_sub}
    )
    assert resp.status_code == 409

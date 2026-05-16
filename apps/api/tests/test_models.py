"""Tests for the model registry endpoints."""

import uuid

from sqlalchemy import select

from vd_db.models import Class, ModelVersion


async def test_list_and_activate_model_syncs_class_indices(client, session):  # type: ignore[no-untyped-def]
    base = ModelVersion(
        kind="yolo", name="base", weights_path="/models/base.pt",
        metrics={"class_names": {"0": "person", "2": "car"}}, is_active=True,
    )
    finetuned = ModelVersion(
        kind="yolo", name="ft", weights_path="/models/ft.pt",
        metrics={"class_names": {"0": "person", "1": "car", "2": "dog"}}, is_active=False,
    )
    session.add_all([base, finetuned])
    await session.commit()

    listing = await client.get("/api/models?kind=yolo")
    assert listing.status_code == 200
    assert {m["name"] for m in listing.json()} == {"base", "ft"}

    resp = await client.post(f"/api/models/{finetuned.id}/activate")
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True

    await session.refresh(base)
    assert base.is_active is False

    # classes.yolo_class_index now matches the activated model's class list.
    person = await session.scalar(select(Class).where(Class.name == "person"))
    dog = await session.scalar(select(Class).where(Class.name == "dog"))
    bear = await session.scalar(select(Class).where(Class.name == "bear"))
    assert person.yolo_class_index == 0
    assert dog.yolo_class_index == 2
    assert bear.yolo_class_index is None  # absent from the model


async def test_activate_missing_model_returns_404(client):  # type: ignore[no-untyped-def]
    resp = await client.post(f"/api/models/{uuid.uuid4()}/activate")
    assert resp.status_code == 404

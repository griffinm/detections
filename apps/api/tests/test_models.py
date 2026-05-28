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
    body = listing.json()
    assert {m["name"] for m in body["items"]} == {"base", "ft"}
    assert body["total"] == 2
    assert body["next_cursor"] is None

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


async def test_list_models_filters_by_kind_and_is_active(client, session):  # type: ignore[no-untyped-def]
    session.add_all([
        ModelVersion(kind="yolo", name="yolo-active", weights_path="/m/y1.pt", is_active=True),
        ModelVersion(kind="yolo", name="yolo-old", weights_path="/m/y2.pt", is_active=False),
        ModelVersion(kind="classifier", name="clf-active", weights_path="/m/c1.pt", is_active=True),
        ModelVersion(kind="classifier", name="clf-old", weights_path="/m/c2.pt", is_active=False),
    ])
    await session.commit()

    yolo_only = await client.get("/api/models?kind=yolo")
    assert yolo_only.status_code == 200
    assert {m["name"] for m in yolo_only.json()["items"]} == {"yolo-active", "yolo-old"}

    active_only = await client.get("/api/models?is_active=true")
    assert active_only.status_code == 200
    assert {m["name"] for m in active_only.json()["items"]} == {"yolo-active", "clf-active"}

    inactive_classifiers = await client.get(
        "/api/models?kind=classifier&is_active=false"
    )
    assert inactive_classifiers.status_code == 200
    body = inactive_classifiers.json()
    assert [m["name"] for m in body["items"]] == ["clf-old"]
    assert body["total"] == 1


async def test_list_models_paginates_with_cursor(client, session):  # type: ignore[no-untyped-def]
    session.add_all([
        ModelVersion(kind="yolo", name=f"m{i}", weights_path=f"/m/{i}.pt", is_active=False)
        for i in range(5)
    ])
    await session.commit()

    page1 = await client.get("/api/models?limit=2")
    assert page1.status_code == 200
    body1 = page1.json()
    assert len(body1["items"]) == 2
    assert body1["total"] == 5
    assert body1["next_cursor"] is not None

    page2 = await client.get(f"/api/models?limit=2&cursor={body1['next_cursor']}")
    assert page2.status_code == 200
    body2 = page2.json()
    assert len(body2["items"]) == 2
    assert body2["next_cursor"] is not None

    # Pages must not overlap.
    page1_ids = {m["id"] for m in body1["items"]}
    page2_ids = {m["id"] for m in body2["items"]}
    assert page1_ids.isdisjoint(page2_ids)


async def test_activate_missing_model_returns_404(client):  # type: ignore[no-untyped-def]
    resp = await client.post(f"/api/models/{uuid.uuid4()}/activate")
    assert resp.status_code == 404

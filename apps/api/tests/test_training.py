"""Tests for the training-runs endpoints and the auto-trigger service."""

import uuid

from sqlalchemy import select

from api.services.training_service import maybe_trigger_finetune
from vd_db.models import Class, Clip, DetectionModel, Frame, TrainingRun


async def test_create_yolo_run_enqueues_task(client, monkeypatch):  # type: ignore[no-untyped-def]
    enqueued: list = []
    monkeypatch.setattr(
        "api.routers.training.enqueue",
        lambda name, *args, **kw: enqueued.append((name, args)),
    )
    resp = await client.post("/api/training-runs", json={"kind": "yolo"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "queued"
    assert ("vd.finetune_yolo", (body["id"],)) in enqueued


async def test_classifier_run_requires_target_class(client):  # type: ignore[no-untyped-def]
    resp = await client.post("/api/training-runs", json={"kind": "classifier"})
    assert resp.status_code == 422


async def test_create_run_rejects_unknown_kind(client):  # type: ignore[no-untyped-def]
    resp = await client.post("/api/training-runs", json={"kind": "bogus"})
    assert resp.status_code == 422


async def test_list_and_get_training_run(client, session):  # type: ignore[no-untyped-def]
    run = TrainingRun(kind="yolo", status="succeeded")
    session.add(run)
    await session.commit()

    listing = await client.get("/api/training-runs")
    assert any(r["id"] == str(run.id) for r in listing.json())

    detail = await client.get(f"/api/training-runs/{run.id}")
    assert detail.status_code == 200
    assert detail.json()["log_tail"] is None


async def test_get_missing_run_returns_404(client):  # type: ignore[no-untyped-def]
    resp = await client.get(f"/api/training-runs/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_auto_trigger_finetune_fires_once(session, monkeypatch):  # type: ignore[no-untyped-def]
    enqueued: list = []
    monkeypatch.setattr(
        "api.services.training_service.enqueue",
        lambda name, *args, **kw: enqueued.append(name),
    )
    # Unique name — `classes` is not truncated between tests (seeded builtins).
    deer = Class(name=f"custom-{uuid.uuid4().hex}", source="custom", is_active=True)
    session.add(deer)
    await session.flush()
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
    for _ in range(100):  # the default custom_class_finetune_threshold
        session.add(
            DetectionModel(
                frame_id=frame.id, class_id=deer.id, predicted_class_id=deer.id,
                bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
                source="user", reviewed=True,
            )
        )
    await session.commit()

    await maybe_trigger_finetune(session)
    assert enqueued == ["vd.finetune_yolo"]
    runs = (
        await session.scalars(select(TrainingRun).where(TrainingRun.kind == "yolo"))
    ).all()
    assert len(runs) == 1

    # A second call dedups — a run is already queued.
    enqueued.clear()
    await maybe_trigger_finetune(session)
    assert enqueued == []

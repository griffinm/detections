"""Tests for the training-runs endpoints."""

import asyncio
import uuid

from sqlalchemy import select

from vd_db.models import Class, TrainingRun


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


async def test_list_returns_paginated_envelope(client, session):  # type: ignore[no-untyped-def]
    run = TrainingRun(kind="yolo", status="succeeded")
    session.add(run)
    await session.commit()

    listing = await client.get("/api/training-runs")
    body = listing.json()
    assert set(body.keys()) == {"items", "total", "next_cursor"}
    assert any(r["id"] == str(run.id) for r in body["items"])
    assert body["total"] >= 1


async def test_get_missing_run_returns_404(client):  # type: ignore[no-untyped-def]
    resp = await client.get(f"/api/training-runs/{uuid.uuid4()}")
    assert resp.status_code == 404


# ─── Pagination ────────────────────────────────────────────────────────────


async def _seed_runs(session, n: int, kind: str = "yolo", status: str = "succeeded"):
    """Seed `n` runs with monotonic created_at so cursor ordering is deterministic."""
    runs = []
    for i in range(n):
        r = TrainingRun(kind=kind, status=status)
        session.add(r)
        runs.append(r)
        # Distinct timestamps even at sub-microsecond resolution.
        await session.flush()
        await asyncio.sleep(0.001)
    await session.commit()
    return runs


async def test_cursor_pagination_round_trip(client, session):  # type: ignore[no-untyped-def]
    await _seed_runs(session, 5)
    page1 = (await client.get("/api/training-runs?limit=2")).json()
    assert len(page1["items"]) == 2
    assert page1["next_cursor"] is not None

    page2 = (
        await client.get(f"/api/training-runs?limit=2&cursor={page1['next_cursor']}")
    ).json()
    assert len(page2["items"]) == 2
    seen = {r["id"] for r in page1["items"]} | {r["id"] for r in page2["items"]}
    assert len(seen) == 4, "pages must not overlap"

    page3 = (
        await client.get(f"/api/training-runs?limit=2&cursor={page2['next_cursor']}")
    ).json()
    assert len(page3["items"]) == 1
    assert page3["next_cursor"] is None, "last page reports no next cursor"


async def test_cursor_survives_anchor_deletion(client, session):  # type: ignore[no-untyped-def]
    runs = await _seed_runs(session, 4)
    page1 = (await client.get("/api/training-runs?limit=2")).json()
    cursor = page1["next_cursor"]
    seen_first = {r["id"] for r in page1["items"]}

    # The cursor anchor is the *last visible row on page 1*, i.e. the second-newest
    # of the seeded runs. Deleting it must not break continuation: keyset paging is
    # "rows strictly older than (value, id)", and that anchor can still be ordered
    # against even after deletion.
    anchor_id = page1["items"][-1]["id"]
    anchor = next(r for r in runs if str(r.id) == anchor_id)
    await session.delete(anchor)
    await session.commit()

    page2 = (
        await client.get(f"/api/training-runs?limit=2&cursor={cursor}")
    ).json()
    seen_second = {r["id"] for r in page2["items"]}
    assert not (seen_first & seen_second), "anchor-after deletion must not re-emit"
    assert len(seen_second) == 2


async def test_status_filter_translates_buckets(client, session):  # type: ignore[no-untyped-def]
    await _seed_runs(session, 2, status="succeeded")
    await _seed_runs(session, 1, status="failed")
    await _seed_runs(session, 1, status="running")

    done = (await client.get("/api/training-runs?status=done")).json()
    failed = (await client.get("/api/training-runs?status=failed")).json()
    running = (await client.get("/api/training-runs?status=running")).json()
    assert all(r["status"] in ("succeeded", "done") for r in done["items"])
    assert all(r["status"] == "failed" for r in failed["items"])
    assert all(r["status"] == "running" for r in running["items"])


async def test_kind_and_cursor_interplay(client, session):  # type: ignore[no-untyped-def]
    class_id = uuid.uuid4()
    cls = Class(id=class_id, name=f"k-{uuid.uuid4().hex}", source="custom", is_active=True)
    session.add(cls)
    await session.flush()
    await _seed_runs(session, 2, kind="yolo")
    await _seed_runs(session, 3, kind="classifier", status="succeeded")
    # The classifier seeder doesn't set target_class_id — patch one row to point
    # at our class so the query reflects a realistic mix.
    sample = (
        await session.scalars(select(TrainingRun).where(TrainingRun.kind == "classifier"))
    ).first()
    assert sample is not None
    sample.target_class_id = class_id
    await session.commit()

    p1 = (await client.get("/api/training-runs?kind=classifier&limit=2")).json()
    p2 = (
        await client.get(f"/api/training-runs?kind=classifier&limit=2&cursor={p1['next_cursor']}")
    ).json()
    ids = {r["id"] for r in p1["items"]} | {r["id"] for r in p2["items"]}
    assert len(ids) == 3
    assert all(r["kind"] == "classifier" for r in [*p1["items"], *p2["items"]])


async def test_malformed_cursor_returns_400(client):  # type: ignore[no-untyped-def]
    resp = await client.get("/api/training-runs?cursor=not-a-real-cursor")
    assert resp.status_code == 400


# ─── Counts endpoint ────────────────────────────────────────────────────────


async def test_counts_bucket_sums(client, session):  # type: ignore[no-untyped-def]
    await _seed_runs(session, 2, status="succeeded")
    await _seed_runs(session, 1, status="failed")
    await _seed_runs(session, 1, status="running")
    await _seed_runs(session, 1, status="queued")

    counts = (await client.get("/api/training-runs/counts")).json()
    assert counts["done"] == 2
    assert counts["failed"] == 1
    assert counts["running"] == 1
    assert counts["queued"] == 1
    assert counts["all"] == counts["done"] + counts["failed"] + counts["running"] + counts["queued"]


async def test_counts_respects_kind_filter(client, session):  # type: ignore[no-untyped-def]
    await _seed_runs(session, 2, kind="yolo", status="succeeded")
    await _seed_runs(session, 3, kind="classifier", status="succeeded")
    yolo = (await client.get("/api/training-runs/counts?kind=yolo")).json()
    cls = (await client.get("/api/training-runs/counts?kind=classifier")).json()
    assert yolo["all"] == 2
    assert cls["all"] == 3



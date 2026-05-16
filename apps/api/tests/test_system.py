"""Tests for the system disk-usage and purge endpoints."""


async def test_disk_usage_shape(client):  # type: ignore[no-untyped-def]
    resp = await client.get("/api/system/disk")
    assert resp.status_code == 200
    body = resp.json()
    assert {"dirs", "total_bytes", "free_bytes"} <= body.keys()
    assert {d["name"] for d in body["dirs"]} == {
        "inbox",
        "processed",
        "frames",
        "models",
    }
    assert body["total_bytes"] > 0


async def test_purge_frames_enqueues_task(client, monkeypatch):  # type: ignore[no-untyped-def]
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "api.routers.system.enqueue", lambda *a, **k: calls.append(a)
    )
    resp = await client.post("/api/system/purge-frames", json={"older_than_days": 14})
    assert resp.status_code == 202
    assert resp.json() == {"enqueued": True, "older_than_days": 14}
    assert calls and calls[0][0] == "vd.purge_frames"


async def test_purge_rejects_non_positive_days(client):  # type: ignore[no-untyped-def]
    resp = await client.post("/api/system/purge-frames", json={"older_than_days": 0})
    assert resp.status_code == 422

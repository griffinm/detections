"""Tests for clip deletion."""

import uuid

from vd_db.models import Clip


async def _seed_clip(session) -> Clip:  # type: ignore[no-untyped-def]
    clip = Clip(
        filename="t.mp4",
        original_path="/in/t.mp4",
        sha256=uuid.uuid4().hex,
        size_bytes=1,
        status="done",
    )
    session.add(clip)
    await session.commit()
    return clip


async def test_delete_clip_enqueues_task(client, session, monkeypatch):  # type: ignore[no-untyped-def]
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "api.routers.clips.enqueue", lambda *a, **k: calls.append(a)
    )
    clip = await _seed_clip(session)

    resp = await client.delete(f"/api/clips/{clip.id}")
    assert resp.status_code == 202
    assert resp.json()["clip_id"] == str(clip.id)
    assert calls and calls[0] == ("vd.delete_clip", str(clip.id))


async def test_delete_missing_clip_is_404(client):  # type: ignore[no-untyped-def]
    resp = await client.delete(f"/api/clips/{uuid.uuid4()}")
    assert resp.status_code == 404

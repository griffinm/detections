"""Tests for clip deletion and upload."""

import uuid
from pathlib import Path

import pytest

from api.routers import clips
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


@pytest.fixture
def inbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the upload endpoint at a throwaway inbox directory."""
    box = tmp_path / "inbox"
    monkeypatch.setattr(clips.settings, "inbox_dir", box)
    return box


async def test_upload_writes_video_to_inbox(client, inbox):  # type: ignore[no-untyped-def]
    resp = await client.post(
        "/api/clips/upload",
        files={"file": ("cat.mp4", b"\x00\x01video-bytes", "video/mp4")},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body == {"filename": "cat.mp4", "size_bytes": 12}

    # The finished video is in the inbox; no partial `.part` file lingers.
    assert (inbox / "cat.mp4").read_bytes() == b"\x00\x01video-bytes"
    assert list(inbox.glob(".upload-*")) == []


async def test_upload_rejects_non_video(client, inbox):  # type: ignore[no-untyped-def]
    resp = await client.post(
        "/api/clips/upload",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 415
    assert not inbox.exists() or list(inbox.iterdir()) == []


async def test_upload_rejects_empty_file(client, inbox):  # type: ignore[no-untyped-def]
    resp = await client.post(
        "/api/clips/upload",
        files={"file": ("empty.mp4", b"", "video/mp4")},
    )
    assert resp.status_code == 422
    assert list(inbox.glob("*")) == []  # nothing left behind


async def test_upload_suffixes_on_name_collision(client, inbox):  # type: ignore[no-untyped-def]
    first = await client.post(
        "/api/clips/upload",
        files={"file": ("clip.mp4", b"one", "video/mp4")},
    )
    second = await client.post(
        "/api/clips/upload",
        files={"file": ("clip.mp4", b"two", "video/mp4")},
    )
    assert first.json()["filename"] == "clip.mp4"
    assert second.json()["filename"] == "clip-1.mp4"
    assert (inbox / "clip.mp4").read_bytes() == b"one"
    assert (inbox / "clip-1.mp4").read_bytes() == b"two"

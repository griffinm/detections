"""Tests for clip deletion and upload."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from api.routers import clips
from vd_db.models import Class, Clip, DetectionModel, Frame


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


async def test_reextract_enqueues_task(  # type: ignore[no-untyped-def]
    client, session, monkeypatch, tmp_path: Path,
):
    """The button on /clips/:id enqueues `vd.reextract_frames` so the worker
    can wipe + re-process the clip."""
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "api.routers.clips.enqueue", lambda *a, **k: calls.append(a)
    )
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    clip = Clip(
        filename="v.mp4", original_path="/in/v.mp4", final_path=str(video),
        sha256=uuid.uuid4().hex, size_bytes=1, status="done",
    )
    session.add(clip)
    await session.commit()

    resp = await client.post(f"/api/clips/{clip.id}/reextract")
    assert resp.status_code == 202
    assert resp.json()["clip_id"] == str(clip.id)
    assert calls and calls[0] == ("vd.reextract_frames", str(clip.id))


async def test_reextract_409s_when_source_video_missing(  # type: ignore[no-untyped-def]
    client, session, monkeypatch,
):
    """The worker needs the original bytes; without them, re-extract is a 409."""
    monkeypatch.setattr("api.routers.clips.enqueue", lambda *a, **k: None)
    clip = Clip(
        filename="v.mp4", original_path="/in/v.mp4", final_path="/nonexistent/v.mp4",
        sha256=uuid.uuid4().hex, size_bytes=1, status="done",
    )
    session.add(clip)
    await session.commit()

    resp = await client.post(f"/api/clips/{clip.id}/reextract")
    assert resp.status_code == 409


async def test_reextract_missing_clip_is_404(client):  # type: ignore[no-untyped-def]
    resp = await client.post(f"/api/clips/{uuid.uuid4()}/reextract")
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
    assert body == {"filename": "cat.mp4", "size_bytes": 13}

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


async def _seed_clip_with_detections(session, frame_count=3):  # type: ignore[no-untyped-def]
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    car = await session.scalar(select(Class.id).where(Class.name == "car"))
    clip = Clip(
        filename="t.mp4", original_path="/in/t.mp4",
        sha256=uuid.uuid4().hex, size_bytes=1, status="done",
    )
    session.add(clip)
    await session.flush()
    dets: list[DetectionModel] = []
    for i in range(frame_count):
        frame = Frame(
            clip_id=clip.id, frame_index=i, timestamp_sec=float(i),
            path=f"{clip.id}/frame_{i:06d}.jpg", width=640, height=480,
            kept=True, detect_status="done",
        )
        session.add(frame)
        await session.flush()
        # Two person + one car so summary ordering is meaningful.
        cls = person if i < 2 else car
        det = DetectionModel(
            frame_id=frame.id, class_id=cls, predicted_class_id=cls,
            bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, source="model",
            confidence_class=0.5,
        )
        session.add(det)
        dets.append(det)
    await session.commit()
    return clip, dets, person, car


async def test_clip_detections_orders_by_frame_index(client, session):  # type: ignore[no-untyped-def]
    clip, dets, _, _ = await _seed_clip_with_detections(session, frame_count=3)
    resp = await client.get(f"/api/clips/{clip.id}/detections")
    assert resp.status_code == 200
    items = resp.json()
    assert [i["id"] for i in items] == [str(d.id) for d in dets]


async def test_clip_detections_filtered_by_class(client, session):  # type: ignore[no-untyped-def]
    clip, dets, person, _ = await _seed_clip_with_detections(session, frame_count=3)
    resp = await client.get(f"/api/clips/{clip.id}/detections?class_id={person}")
    items = resp.json()
    # First two are person, third is car
    assert [i["id"] for i in items] == [str(dets[0].id), str(dets[1].id)]


async def test_clip_class_summary(client, session):  # type: ignore[no-untyped-def]
    clip, _, person, car = await _seed_clip_with_detections(session, frame_count=3)
    resp = await client.get(f"/api/clips/{clip.id}/class-summary")
    rows = resp.json()
    by_id = {r["class_id"]: r for r in rows}
    assert by_id[str(person)]["count"] == 2
    assert by_id[str(car)]["count"] == 1
    # most-common-first ordering powers the page's default filter pick
    assert rows[0]["class_id"] == str(person)


async def test_clip_detections_404_for_missing_clip(client):  # type: ignore[no-untyped-def]
    resp = await client.get(f"/api/clips/{uuid.uuid4()}/detections")
    assert resp.status_code == 404


async def test_clip_overlay_returns_lean_shape_ordered_by_frame(  # type: ignore[no-untyped-def]
    client, session,
):
    """The overlay endpoint feeds the in-app player: per-detection frame_index
    and track_id, no image URLs."""
    clip, dets, person, car = await _seed_clip_with_detections(session, frame_count=3)
    resp = await client.get(f"/api/clips/{clip.id}/overlay")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == len(dets)
    assert [i["frame_index"] for i in items] == [0, 1, 2]
    assert [i["class_id"] for i in items] == [
        str(person), str(person), str(car),
    ]
    # Lean shape: only the fields the player needs.
    assert set(items[0].keys()) == {
        "frame_index", "bbox", "class_id", "subclass_id",
        "track_id", "confidence_class",
    }


async def test_clip_overlay_404_for_missing_clip(client):  # type: ignore[no-untyped-def]
    resp = await client.get(f"/api/clips/{uuid.uuid4()}/overlay")
    assert resp.status_code == 404


async def test_clip_video_streams_file_with_range_support(  # type: ignore[no-untyped-def]
    client, session, tmp_path: Path,
):
    """The player needs `Accept-Ranges: bytes` (for seek) and a video/* MIME
    type. Starlette's FileResponse provides both for free."""
    video = tmp_path / "v.mp4"
    payload = b"\x00\x01\x02\x03\x04\x05" * 2048  # 12 KiB
    video.write_bytes(payload)
    clip = Clip(
        filename="v.mp4", original_path="/in/v.mp4", final_path=str(video),
        sha256=uuid.uuid4().hex, size_bytes=len(payload), status="done",
    )
    session.add(clip)
    await session.commit()

    head = await client.head(f"/api/clips/{clip.id}/video")
    assert head.status_code == 200
    assert head.headers.get("accept-ranges") == "bytes"
    assert head.headers["content-type"].startswith("video/")

    ranged = await client.get(
        f"/api/clips/{clip.id}/video", headers={"Range": "bytes=0-1023"},
    )
    assert ranged.status_code == 206
    assert len(ranged.content) == 1024
    assert ranged.content == payload[:1024]


async def test_clip_video_404_when_final_path_missing(  # type: ignore[no-untyped-def]
    client, session,
):
    """A clip whose source file was purged still has a row, but the player
    endpoint must surface that the bytes are gone."""
    clip = Clip(
        filename="v.mp4", original_path="/in/v.mp4", final_path=None,
        sha256=uuid.uuid4().hex, size_bytes=1, status="done",
    )
    session.add(clip)
    await session.commit()

    resp = await client.get(f"/api/clips/{clip.id}/video")
    assert resp.status_code == 404


async def test_clip_video_404_when_file_gone(  # type: ignore[no-untyped-def]
    client, session,
):
    clip = Clip(
        filename="v.mp4", original_path="/in/v.mp4",
        final_path="/nonexistent/v.mp4",
        sha256=uuid.uuid4().hex, size_bytes=1, status="done",
    )
    session.add(clip)
    await session.commit()
    resp = await client.get(f"/api/clips/{clip.id}/video")
    assert resp.status_code == 404

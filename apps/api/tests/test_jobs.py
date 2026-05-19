"""Tests for the external integration API (`POST/GET /api/jobs`)."""

import uuid

from sqlalchemy import select

from vd_db.models import Class, Clip, DetectionModel, Frame


def _intake(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """Point the router at a writable intake dir and return it."""
    intake = tmp_path / "intake"
    intake.mkdir()
    monkeypatch.setattr("api.routers.jobs.settings.intake_dir", intake)
    return intake


async def test_create_job(client, session, monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    intake = _intake(tmp_path, monkeypatch)
    video = intake / "evt.mp4"
    video.write_bytes(b"fake-video")
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr("api.routers.jobs.enqueue", lambda *a, **k: calls.append(a))

    resp = await client.post(
        "/api/jobs",
        json={
            "source": "unifi-protect",
            "video_path": str(video),
            "external_id": "evt_1",
            "callback_url": "http://hook.example/cb",
            "metadata": {"zone": "driveway"},
        },
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "pending"

    assert calls and calls[0][0] == "vd.ingest_video"
    assert calls[0][2] == body["job_id"]  # (name, video_path, clip_id)

    clip = await session.get(Clip, uuid.UUID(body["job_id"]))
    assert clip is not None
    assert clip.source == "unifi-protect"
    assert clip.external_id == "evt_1"
    assert "hook.example" in (clip.callback_url or "")
    assert clip.external_metadata == {"zone": "driveway"}
    assert clip.sha256 is None  # the worker fills this in


async def test_create_job_is_idempotent(client, monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    intake = _intake(tmp_path, monkeypatch)
    video = intake / "evt.mp4"
    video.write_bytes(b"fake-video")
    payload = {"source": "unifi-protect", "video_path": str(video), "external_id": "dup"}

    first = await client.post("/api/jobs", json=payload)
    second = await client.post("/api/jobs", json=payload)
    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]


async def test_path_outside_intake_rejected(client, monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    _intake(tmp_path, monkeypatch)
    outside = tmp_path / "evil.mp4"
    outside.write_bytes(b"x")
    resp = await client.post(
        "/api/jobs", json={"source": "x", "video_path": str(outside)}
    )
    assert resp.status_code == 422


async def test_missing_video_rejected(client, monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    intake = _intake(tmp_path, monkeypatch)
    resp = await client.post(
        "/api/jobs", json={"source": "x", "video_path": str(intake / "nope.mp4")}
    )
    assert resp.status_code == 422


async def test_get_job_pending(client, session):  # type: ignore[no-untyped-def]
    clip = Clip(
        filename="t.mp4", original_path="/in/t.mp4", size_bytes=1,
        status="pending", source="family-archive", external_id="fa_1",
    )
    session.add(clip)
    await session.commit()

    resp = await client.get(f"/api/jobs/{clip.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == str(clip.id)
    assert body["status"] == "pending"
    assert body["source"] == "family-archive"
    assert "detections" not in body  # in-flight → status only


async def test_get_missing_job_is_404(client):  # type: ignore[no-untyped-def]
    resp = await client.get(f"/api/jobs/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_get_job_result_with_detections(client, session):  # type: ignore[no-untyped-def]
    clip = Clip(
        filename="t.mp4", original_path="/in/t.mp4", size_bytes=1, status="done",
        source="family-archive", duration_sec=8, width=1920, height=1080,
    )
    session.add(clip)
    await session.flush()
    frame = Frame(
        clip_id=clip.id, frame_index=1, timestamp_sec=1, width=1920, height=1080,
        kept=True, detect_status="done",
    )
    session.add(frame)
    await session.flush()
    person = await session.scalar(select(Class).where(Class.name == "person"))
    session.add(
        DetectionModel(
            frame_id=frame.id, class_id=person.id,
            bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.3},
            confidence_class=0.9, source="model",
        )
    )
    await session.commit()

    resp = await client.get(f"/api/jobs/{clip.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "done"
    assert body["clip"]["width"] == 1920
    assert len(body["detections"]) == 1
    assert body["detections"][0]["class"] == "person"
    assert body["summary"]["classes"] == [{"class": "person", "frames": 1}]

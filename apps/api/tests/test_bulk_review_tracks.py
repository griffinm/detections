"""Tests for `POST /api/labeling/bulk-review-tracks`."""

import uuid

from sqlalchemy import select

from vd_db.models import (
    Class,
    Clip,
    DetectionModel,
    Frame,
    Subclass,
    Track,
    TrackAudit,
)


async def _seed(session, n_clips=2, frames_per_clip=2):  # type: ignore[no-untyped-def]
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    sub = Subclass(class_id=person, name="Mallory")
    session.add(sub)
    await session.flush()
    tracks = []
    for c in range(n_clips):
        clip = Clip(
            filename=f"c{c}.mp4", original_path=f"/in/c{c}.mp4",
            sha256=uuid.uuid4().hex, size_bytes=1, status="done",
        )
        session.add(clip)
        await session.flush()
        frames = []
        for i in range(frames_per_clip):
            fr = Frame(
                clip_id=clip.id, frame_index=i, timestamp_sec=float(i),
                path=f"{clip.id}/f{i}.jpg", width=10, height=10,
                kept=True, detect_status="done",
            )
            session.add(fr)
            frames.append(fr)
        await session.flush()
        track = Track(
            clip_id=clip.id, class_id=person, predicted_class_id=person,
            source="tracker", first_frame_index=0,
            last_frame_index=frames_per_clip - 1,
            n_detections=frames_per_clip, confidence_class=0.9,
        )
        session.add(track)
        await session.flush()
        for fr in frames:
            session.add(
                DetectionModel(
                    frame_id=fr.id, class_id=person, predicted_class_id=person,
                    bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, source="model",
                    confidence_class=0.9, track_id=track.id,
                )
            )
        tracks.append(track)
    await session.commit()
    return person, sub, tracks


async def test_bulk_review_tracks_marks_all_members(client, session):  # type: ignore[no-untyped-def]
    _person, sub, tracks = await _seed(session, n_clips=3, frames_per_clip=4)

    resp = await client.post(
        "/api/labeling/bulk-review-tracks",
        json={
            "track_ids": [str(t.id) for t in tracks],
            "subclass_id": str(sub.id),
            "reviewed": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["updated_tracks"] == 3
    assert body["updated_detections"] == 12  # 3 tracks × 4 members
    assert body["skipped_tracks"] == 0
    assert len(body["affected_track_ids"]) == 3

    session.expunge_all()
    dets = list(await session.scalars(select(DetectionModel)))
    assert all(d.subclass_id == sub.id and d.reviewed for d in dets)
    refreshed_tracks = list(await session.scalars(select(Track)))
    assert all(t.reviewed and t.subclass_id == sub.id for t in refreshed_tracks)


async def test_bulk_review_tracks_is_idempotent(client, session):  # type: ignore[no-untyped-def]
    _person, sub, tracks = await _seed(session, n_clips=2, frames_per_clip=2)

    body = {
        "track_ids": [str(t.id) for t in tracks],
        "subclass_id": str(sub.id),
        "reviewed": True,
    }
    first = (await client.post("/api/labeling/bulk-review-tracks", json=body)).json()
    second = (await client.post("/api/labeling/bulk-review-tracks", json=body)).json()

    assert first["updated_tracks"] == 2
    # Re-applying the same state changes nothing — and writes zero audits.
    assert second["updated_tracks"] == 0
    assert second["audits_written"] == 0

    audits = list(await session.scalars(select(TrackAudit)))
    # Two reasons per track on first apply: user_reassign + user_review.
    assert len(audits) == 4

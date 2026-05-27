"""Tests for `/api/tracks/*` — PATCH propagation, split, merge, delete."""

import uuid

from sqlalchemy import select

from vd_db.models import (
    Class,
    Clip,
    DetectionAudit,
    DetectionModel,
    Frame,
    Subclass,
    Track,
    TrackAudit,
)


async def _seed_clip(session, n_frames=3):  # type: ignore[no-untyped-def]
    clip = Clip(
        filename="t.mp4", original_path="/in/t.mp4",
        sha256=uuid.uuid4().hex, size_bytes=1, status="done",
    )
    session.add(clip)
    await session.flush()
    frames = []
    for i in range(n_frames):
        fr = Frame(
            clip_id=clip.id, frame_index=i, timestamp_sec=float(i),
            path=f"{clip.id}/f{i}.jpg", width=10, height=10,
            kept=True, detect_status="done",
        )
        session.add(fr)
        frames.append(fr)
    await session.flush()
    return clip, frames


async def _class_id(session, name):  # type: ignore[no-untyped-def]
    return await session.scalar(select(Class.id).where(Class.name == name))


async def _make_track(session, clip, class_id, frames, subclass_id=None):  # type: ignore[no-untyped-def]
    track = Track(
        clip_id=clip.id, class_id=class_id, subclass_id=subclass_id,
        predicted_class_id=class_id, predicted_subclass_id=subclass_id,
        source="tracker", first_frame_index=frames[0].frame_index,
        last_frame_index=frames[-1].frame_index, n_detections=len(frames),
        confidence_class=0.9,
    )
    session.add(track)
    await session.flush()
    for fr in frames:
        det = DetectionModel(
            frame_id=fr.id, class_id=class_id, predicted_class_id=class_id,
            subclass_id=subclass_id, predicted_subclass_id=subclass_id,
            bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, source="model",
            confidence_class=0.9, track_id=track.id,
        )
        session.add(det)
    await session.flush()
    return track


async def test_get_clip_tracks(client, session):  # type: ignore[no-untyped-def]
    clip, frames = await _seed_clip(session, n_frames=4)
    person = await _class_id(session, "person")
    car = await _class_id(session, "car")
    await _make_track(session, clip, person, frames[:2])
    await _make_track(session, clip, car, frames[2:])
    await session.commit()

    resp = await client.get(f"/api/clips/{clip.id}/tracks")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    # Ordered by first_frame_index ascending.
    assert body[0]["first_frame_index"] == 0
    assert body[1]["first_frame_index"] == 2


async def test_patch_track_propagates_to_members(client, session):  # type: ignore[no-untyped-def]
    clip, frames = await _seed_clip(session, n_frames=3)
    person = await _class_id(session, "person")
    sub = Subclass(class_id=person, name="Mallory")
    session.add(sub)
    await session.flush()
    track = await _make_track(session, clip, person, frames)
    await session.commit()

    resp = await client.patch(
        f"/api/tracks/{track.id}",
        json={"subclass_id": str(sub.id), "reviewed": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["track"]["subclass_id"] == str(sub.id)
    assert body["track"]["reviewed"] is True
    assert body["updated_detections"] == 3

    session.expunge_all()
    dets = list(await session.scalars(select(DetectionModel)))
    assert all(d.subclass_id == sub.id and d.reviewed for d in dets)

    # Per-detection audits + 2 track-level audits (reassign + review).
    det_audit_count = await session.scalar(
        select(__import__("sqlalchemy").func.count()).select_from(DetectionAudit)
    )
    track_audits = list(
        await session.scalars(
            select(TrackAudit).where(TrackAudit.track_id == track.id)
        )
    )
    assert det_audit_count >= 3  # at least one per member (re-class triggers user_reassign)
    reasons = sorted(a.reason for a in track_audits)
    assert "user_reassign" in reasons and "user_review" in reasons


async def test_split_track_carves_off_new_track(client, session):  # type: ignore[no-untyped-def]
    clip, frames = await _seed_clip(session, n_frames=5)
    person = await _class_id(session, "person")
    track = await _make_track(session, clip, person, frames)
    await session.commit()
    original_id = track.id

    resp = await client.post(
        f"/api/tracks/{track.id}/split", json={"pivot_frame_index": 2}
    )
    assert resp.status_code == 200
    new_track = resp.json()["track"]
    assert new_track["first_frame_index"] == 2
    assert new_track["last_frame_index"] == 4
    assert new_track["n_detections"] == 3
    assert new_track["source"] == "user"

    session.expunge_all()
    original = await session.get(Track, original_id)
    assert original is not None
    assert original.first_frame_index == 0
    assert original.last_frame_index == 1
    assert original.n_detections == 2

    # Audit on the NEW track records the structural event.
    audits = list(
        await session.scalars(
            select(TrackAudit).where(TrackAudit.reason == "user_split")
        )
    )
    assert len(audits) == 1
    assert audits[0].from_track_id == original_id
    assert audits[0].pivot_frame_index == 2
    assert audits[0].n_detections_moved == 3


async def test_split_pivot_at_edge_is_rejected(client, session):  # type: ignore[no-untyped-def]
    clip, frames = await _seed_clip(session, n_frames=3)
    person = await _class_id(session, "person")
    track = await _make_track(session, clip, person, frames)
    await session.commit()

    # Pivot at the first frame would leave the original empty.
    resp = await client.post(
        f"/api/tracks/{track.id}/split", json={"pivot_frame_index": 0}
    )
    assert resp.status_code == 422


async def test_merge_two_tracks_combines_them(client, session):  # type: ignore[no-untyped-def]
    clip, frames = await _seed_clip(session, n_frames=5)
    person = await _class_id(session, "person")
    target = await _make_track(session, clip, person, frames[:2])
    other = await _make_track(session, clip, person, frames[3:])
    await session.commit()
    other_id = other.id

    resp = await client.post(
        f"/api/tracks/{target.id}/merge",
        json={"other_track_id": str(other_id)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["track"]["n_detections"] == 4
    assert body["track"]["first_frame_index"] == 0
    assert body["track"]["last_frame_index"] == 4

    session.expunge_all()
    absorbed = await session.get(Track, other_id)
    assert absorbed is not None and absorbed.deleted_at is not None


async def test_merge_overlapping_ranges_rejected(client, session):  # type: ignore[no-untyped-def]
    clip, frames = await _seed_clip(session, n_frames=4)
    person = await _class_id(session, "person")
    target = await _make_track(session, clip, person, frames[:3])
    other = await _make_track(session, clip, person, frames[1:])
    await session.commit()

    resp = await client.post(
        f"/api/tracks/{target.id}/merge",
        json={"other_track_id": str(other.id)},
    )
    assert resp.status_code == 422


async def test_merge_different_class_rejected(client, session):  # type: ignore[no-untyped-def]
    clip, frames = await _seed_clip(session, n_frames=4)
    person = await _class_id(session, "person")
    car = await _class_id(session, "car")
    target = await _make_track(session, clip, person, frames[:2])
    other = await _make_track(session, clip, car, frames[2:])
    await session.commit()

    resp = await client.post(
        f"/api/tracks/{target.id}/merge",
        json={"other_track_id": str(other.id)},
    )
    assert resp.status_code == 422


async def test_delete_track_soft_deletes_members(client, session):  # type: ignore[no-untyped-def]
    clip, frames = await _seed_clip(session, n_frames=3)
    person = await _class_id(session, "person")
    track = await _make_track(session, clip, person, frames)
    await session.commit()

    resp = await client.delete(f"/api/tracks/{track.id}")
    assert resp.status_code == 204

    session.expunge_all()
    refreshed = await session.get(Track, track.id)
    assert refreshed is not None and refreshed.deleted_at is not None
    dets = list(await session.scalars(select(DetectionModel)))
    assert all(d.deleted_at is not None for d in dets)

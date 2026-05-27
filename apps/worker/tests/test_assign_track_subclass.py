"""Integration tests for `vd.assign_track_subclass`.

Track-level vote across member detections, propagation to unreviewed
model-source detections, and the idempotency guard (re-runs don't write a
fresh audit row when the winner is unchanged).
"""

import uuid

import pytest
from sqlalchemy import select

from vd_db.models import (
    Class,
    Clip,
    DetectionAudit,
    DetectionModel,
    Frame,
    Subclass,
    SubclassExample,
    Track,
)
from worker.tasks import assign_track_subclass as track_mod
from worker.tasks.assign_track_subclass import _assign_track_subclass_async

FACE_DIM = 512


def _onehot(index: int) -> list[float]:
    return [1.0 if k == index else 0.0 for k in range(FACE_DIM)]


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(track_mod, "publish", _noop)


async def _seed_clip_and_frames(session, n_frames):  # type: ignore[no-untyped-def]
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


async def _seed_examples(session, frame, person):  # type: ignore[no-untyped-def]
    """3 'Mallory' (one-hot 0), 2 'Bob' (one-hot 1) example crops."""
    mallory = Subclass(class_id=person, name="Mallory")
    bob = Subclass(class_id=person, name="Bob")
    session.add_all([mallory, bob])
    await session.flush()

    pairs = [(_onehot(0), mallory)] * 3 + [(_onehot(1), bob)] * 2
    for embedding, sub in pairs:
        det = DetectionModel(
            frame_id=frame.id, class_id=person, predicted_class_id=person,
            bbox={"x": 0.3, "y": 0.3, "w": 0.2, "h": 0.2}, source="model",
            confidence_class=0.9, face_embedding=embedding,
        )
        session.add(det)
        await session.flush()
        session.add(SubclassExample(subclass_id=sub.id, detection_id=det.id))
    await session.commit()
    return mallory, bob


async def _make_track(session, clip, person):  # type: ignore[no-untyped-def]
    track = Track(
        clip_id=clip.id, class_id=person, predicted_class_id=person,
        source="tracker", first_frame_index=0, last_frame_index=0,
        n_detections=0, confidence_class=0.9,
    )
    session.add(track)
    await session.flush()
    return track


async def test_track_vote_majority_wins_and_propagates(session):  # type: ignore[no-untyped-def]
    clip, frames = await _seed_clip_and_frames(session, n_frames=3)
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    mallory, bob = await _seed_examples(session, frames[0], person)
    track = await _make_track(session, clip, person)

    # Three track members: two clearly Mallory, one slightly Bob-ish. Track
    # vote should resolve to Mallory and propagate to every member.
    members = []
    for i, embedding in enumerate([_onehot(0), _onehot(0), _onehot(1)]):
        det = DetectionModel(
            frame_id=frames[i].id, class_id=person, predicted_class_id=person,
            bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, source="model",
            confidence_class=0.9, face_embedding=embedding, track_id=track.id,
        )
        session.add(det)
        members.append(det)
    await session.commit()

    assert await _assign_track_subclass_async(str(track.id)) is True

    await session.refresh(track)
    assert track.subclass_id == mallory.id
    assert track.predicted_subclass_id == mallory.id
    assert track.confidence_subclass is not None and track.confidence_subclass > 0.5

    for det in members:
        await session.refresh(det)
        assert det.subclass_id == mallory.id
        assert det.predicted_subclass_id == mallory.id

    audits = list(await session.scalars(
        select(DetectionAudit).where(
            DetectionAudit.detection_id.in_([m.id for m in members])
        )
    ))
    assert len(audits) == 3
    assert all(a.reason == "initial_prediction" for a in audits)
    assert all(a.to_subclass_id == mallory.id for a in audits)


async def test_track_vote_skips_user_reviewed_members(session):  # type: ignore[no-untyped-def]
    """A reviewed member is ground truth — the track vote must not overwrite it."""
    clip, frames = await _seed_clip_and_frames(session, n_frames=2)
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    _mallory, _bob = await _seed_examples(session, frames[0], person)
    track = await _make_track(session, clip, person)

    reviewed_det = DetectionModel(
        frame_id=frames[0].id, class_id=person, predicted_class_id=person,
        bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, source="model",
        confidence_class=0.9, face_embedding=_onehot(0), track_id=track.id,
        reviewed=True,  # already vouched for by the user
    )
    fresh_det = DetectionModel(
        frame_id=frames[1].id, class_id=person, predicted_class_id=person,
        bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, source="model",
        confidence_class=0.9, face_embedding=_onehot(0), track_id=track.id,
    )
    session.add_all([reviewed_det, fresh_det])
    await session.commit()

    assert await _assign_track_subclass_async(str(track.id)) is True

    await session.refresh(reviewed_det)
    assert reviewed_det.subclass_id is None  # untouched

    await session.refresh(fresh_det)
    assert fresh_det.subclass_id is not None  # propagated


async def test_track_vote_idempotent_no_extra_audit_when_unchanged(session):  # type: ignore[no-untyped-def]
    clip, frames = await _seed_clip_and_frames(session, n_frames=2)
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    _mallory, _bob = await _seed_examples(session, frames[0], person)
    track = await _make_track(session, clip, person)

    members = []
    for i in range(2):
        det = DetectionModel(
            frame_id=frames[i].id, class_id=person, predicted_class_id=person,
            bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, source="model",
            confidence_class=0.9, face_embedding=_onehot(0), track_id=track.id,
        )
        session.add(det)
        members.append(det)
    await session.commit()

    assert await _assign_track_subclass_async(str(track.id)) is True
    after_first = len(list(await session.scalars(
        select(DetectionAudit).where(
            DetectionAudit.detection_id.in_([m.id for m in members])
        )
    )))

    # Re-running converges to the same winner — no fresh audit rows.
    assert await _assign_track_subclass_async(str(track.id)) is True
    after_second = len(list(await session.scalars(
        select(DetectionAudit).where(
            DetectionAudit.detection_id.in_([m.id for m in members])
        )
    )))
    assert after_first == after_second


async def test_track_vote_skips_below_threshold(session):  # type: ignore[no-untyped-def]
    """A track whose vote falls below subclass_min_confidence stays untouched."""
    clip, frames = await _seed_clip_and_frames(session, n_frames=2)
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    _mallory, _bob = await _seed_examples(session, frames[0], person)
    track = await _make_track(session, clip, person)

    members = []
    for i in range(2):
        det = DetectionModel(
            frame_id=frames[i].id, class_id=person, predicted_class_id=person,
            bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, source="model",
            # Equidistant from every one-hot example — cosine ~0.044 (< 0.55).
            confidence_class=0.9, face_embedding=[1.0] * FACE_DIM,
            track_id=track.id,
        )
        session.add(det)
        members.append(det)
    await session.commit()

    assert await _assign_track_subclass_async(str(track.id)) is False

    await session.refresh(track)
    assert track.subclass_id is None
    for det in members:
        await session.refresh(det)
        assert det.subclass_id is None

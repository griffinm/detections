"""Integration tests for `vd.assign_subclass` kNN against a real test database.

The embeddings are seeded directly (no GPU / InsightFace needed); the pgvector
cosine-distance query, the top-5 majority vote, the threshold gate, and the
audit row all run for real.
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
    ModelVersion,
    Subclass,
    SubclassExample,
)
from worker.tasks import assign_subclass as assign_mod
from worker.tasks.assign_subclass import _assign_subclass_async

FACE_DIM = 512


def _onehot(index: int) -> list[float]:
    """A unit vector with a single 1.0 — cosine-similar only to its twin."""
    return [1.0 if k == index else 0.0 for k in range(FACE_DIM)]


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(assign_mod, "publish", _noop)


async def _seed_frame(session):  # type: ignore[no-untyped-def]
    clip = Clip(
        filename="t.mp4", original_path="/in/t.mp4",
        sha256=uuid.uuid4().hex, size_bytes=1, status="done",
    )
    session.add(clip)
    await session.flush()
    frame = Frame(
        clip_id=clip.id, frame_index=0, timestamp_sec=0.0,
        path=f"{clip.id}/f.jpg", width=640, height=480,
        kept=True, detect_status="done",
    )
    session.add(frame)
    await session.flush()
    return frame


def _detection(frame, class_id, embedding=None):  # type: ignore[no-untyped-def]
    return DetectionModel(
        frame_id=frame.id, class_id=class_id, predicted_class_id=class_id,
        bbox={"x": 0.3, "y": 0.3, "w": 0.2, "h": 0.2}, source="model",
        confidence_class=0.9, face_embedding=embedding,
    )


async def _seed_examples(session, frame):  # type: ignore[no-untyped-def]
    """3 'Mallory' example crops (one-hot 0), 2 'Bob' (one-hot 1)."""
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    mallory = Subclass(class_id=person, name="Mallory")
    bob = Subclass(class_id=person, name="Bob")
    session.add_all([mallory, bob])
    await session.flush()

    pairs = [(_onehot(0), mallory)] * 3 + [(_onehot(1), bob)] * 2
    for embedding, sub in pairs:
        det = _detection(frame, person, embedding)
        session.add(det)
        await session.flush()
        session.add(SubclassExample(subclass_id=sub.id, detection_id=det.id))
    await session.commit()
    return person, mallory, bob


async def test_assign_subclass_votes_nearest_examples(session):  # type: ignore[no-untyped-def]
    frame = await _seed_frame(session)
    person, mallory, _bob = await _seed_examples(session, frame)

    query = _detection(frame, person, _onehot(0))
    session.add(query)
    await session.commit()

    assert await _assign_subclass_async(str(query.id)) is True

    await session.refresh(query)
    assert query.subclass_id == mallory.id
    assert query.predicted_subclass_id == mallory.id
    assert query.confidence_subclass == pytest.approx(1.0, abs=1e-3)

    audits = (
        await session.scalars(
            select(DetectionAudit).where(DetectionAudit.detection_id == query.id)
        )
    ).all()
    assert [a.reason for a in audits] == ["initial_prediction"]
    assert audits[0].to_subclass_id == mallory.id


async def test_assign_subclass_respects_user_review(session):  # type: ignore[no-untyped-def]
    frame = await _seed_frame(session)
    person, mallory, _bob = await _seed_examples(session, frame)

    query = _detection(frame, person, _onehot(0))
    query.reviewed = True  # user has already vouched for this row
    session.add(query)
    await session.commit()

    assert await _assign_subclass_async(str(query.id)) is True

    await session.refresh(query)
    # Prediction is recorded, but the user-reviewed current value is untouched.
    assert query.predicted_subclass_id == mallory.id
    assert query.subclass_id is None


async def test_assign_subclass_skips_below_threshold(session):  # type: ignore[no-untyped-def]
    frame = await _seed_frame(session)
    person, _mallory, _bob = await _seed_examples(session, frame)

    # Equidistant from every one-hot example — cosine sim ~0.044, below 0.55.
    query = _detection(frame, person, [1.0] * FACE_DIM)
    session.add(query)
    await session.commit()

    assert await _assign_subclass_async(str(query.id)) is False
    await session.refresh(query)
    assert query.subclass_id is None
    assert query.predicted_subclass_id is None


async def test_assign_subclass_noop_without_examples(session):  # type: ignore[no-untyped-def]
    frame = await _seed_frame(session)
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    session.add(Subclass(class_id=person, name="Mallory"))  # no example crops yet

    query = _detection(frame, person, _onehot(0))
    session.add(query)
    await session.commit()

    assert await _assign_subclass_async(str(query.id)) is False


async def test_assign_subclass_uses_active_classifier(session, monkeypatch):  # type: ignore[no-untyped-def]
    """Regime B: an active classifier supersedes the kNN bootstrap."""
    import vd_ml

    frame = await _seed_frame(session)
    person, mallory, _bob = await _seed_examples(session, frame)
    classifier_version = ModelVersion(
        kind="classifier", name="clf", weights_path="/models/clf.joblib",
        target_class_id=person, is_active=True,
    )
    session.add(classifier_version)
    query = _detection(frame, person, _onehot(0))
    session.add(query)
    await session.commit()

    monkeypatch.setattr(vd_ml, "load_classifier", lambda path: object())
    monkeypatch.setattr(
        vd_ml, "predict_subclass", lambda clf, emb: (str(mallory.id), 0.95)
    )

    assert await _assign_subclass_async(str(query.id)) is True

    await session.refresh(query)
    assert query.subclass_id == mallory.id
    audits = (
        await session.scalars(
            select(DetectionAudit).where(DetectionAudit.detection_id == query.id)
        )
    ).all()
    assert audits[0].model_version_id == classifier_version.id

"""Integration test for `vd.train_subclass_classifier` with the fit call faked."""

import uuid

import pytest
import vd_ml
from sqlalchemy import select
from vd_ml.classifier import ClassifierTrainResult

from vd_db.models import Class, Clip, DetectionModel, Frame, ModelVersion, Subclass, TrainingRun

_FACE_DIM = 512


@pytest.fixture(autouse=True)
def _fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(*args: object, **kwargs: object) -> None:
        return None

    from worker.tasks import train_subclass_classifier as tc_mod

    monkeypatch.setattr(tc_mod, "publish", _noop)

    def fake_train(embeddings, labels, out_path):  # type: ignore[no-untyped-def]
        return ClassifierTrainResult(
            val_accuracy=0.9, n_train=len(labels), n_val=0,
            subclass_ids=sorted(set(labels)),
        )

    monkeypatch.setattr(vd_ml, "train_subclass_classifier", fake_train)


async def _frame(session):  # type: ignore[no-untyped-def]
    clip = Clip(
        filename="t.mp4", original_path="/in/t.mp4",
        sha256=uuid.uuid4().hex, size_bytes=1, status="done",
    )
    session.add(clip)
    await session.flush()
    frame = Frame(
        clip_id=clip.id, frame_index=0, timestamp_sec=0.0,
        path=f"{clip.id}/f.jpg", width=640, height=480, kept=True, detect_status="done",
    )
    session.add(frame)
    await session.flush()
    return frame


async def test_classifier_trains_and_activates(session):  # type: ignore[no-untyped-def]
    from worker.tasks.train_subclass_classifier import _train_subclass_classifier_async

    frame = await _frame(session)
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    subs = [Subclass(class_id=person, name=f"p{i}") for i in range(2)]
    session.add_all(subs)
    await session.flush()
    for sub in subs:
        for _ in range(3):
            session.add(
                DetectionModel(
                    frame_id=frame.id, class_id=person, predicted_class_id=person,
                    bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, source="model",
                    reviewed=True, subclass_id=sub.id, confidence_class=0.9,
                    face_embedding=[1.0] * _FACE_DIM,
                )
            )
    run = TrainingRun(kind="classifier", target_class_id=person, status="queued")
    session.add(run)
    await session.commit()

    result = await _train_subclass_classifier_async(str(run.id))
    assert result not in ("failed", "missing")

    await session.refresh(run)
    assert run.status == "succeeded"
    version = await session.scalar(
        select(ModelVersion).where(
            ModelVersion.kind == "classifier", ModelVersion.target_class_id == person
        )
    )
    assert version is not None and version.is_active is True


async def test_classifier_fails_with_one_subclass(session):  # type: ignore[no-untyped-def]
    from worker.tasks.train_subclass_classifier import _train_subclass_classifier_async

    frame = await _frame(session)
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    sub = Subclass(class_id=person, name="only")
    session.add(sub)
    await session.flush()
    session.add(
        DetectionModel(
            frame_id=frame.id, class_id=person, predicted_class_id=person,
            bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, source="model",
            reviewed=True, subclass_id=sub.id, confidence_class=0.9,
            face_embedding=[1.0] * _FACE_DIM,
        )
    )
    run = TrainingRun(kind="classifier", target_class_id=person, status="queued")
    session.add(run)
    await session.commit()

    result = await _train_subclass_classifier_async(str(run.id))
    assert result == "failed"
    await session.refresh(run)
    assert run.status == "failed"

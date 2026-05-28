"""Tests for the auto-trigger that fires sub-class classifier retrains."""

import uuid

from sqlalchemy import select

from api.services.training_service import maybe_trigger_classifier
from vd_db.models import Class, Clip, DetectionModel, Frame, Subclass, TrainingRun


async def _seed_frame(session) -> Frame:  # type: ignore[no-untyped-def]
    clip = Clip(
        filename="t.mp4", original_path="/in/t.mp4",
        sha256=uuid.uuid4().hex, size_bytes=1, status="done",
    )
    session.add(clip)
    await session.flush()
    frame = Frame(
        clip_id=clip.id, frame_index=0, timestamp_sec=0.0,
        path=f"{clip.id}/frame_000000.jpg", width=640, height=480,
        kept=True, detect_status="done",
    )
    session.add(frame)
    await session.flush()
    return frame


async def _add_labeled_detection(
    session,  # type: ignore[no-untyped-def]
    *,
    frame: Frame,
    class_id: uuid.UUID,
    subclass_id: uuid.UUID,
    face_embedding: list[float] | None = None,
    object_embedding: list[float] | None = None,
) -> DetectionModel:
    det = DetectionModel(
        frame_id=frame.id,
        class_id=class_id,
        subclass_id=subclass_id,
        bbox={"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.4},
        source="user",
        reviewed=True,
        face_embedding=face_embedding,
        object_embedding=object_embedding,
    )
    session.add(det)
    return det


async def test_person_trigger_ignores_labels_with_no_face_embedding(session):  # type: ignore[no-untyped-def]
    """Regression: counting all labeled rows let `labeled` permanently outrun
    `trained_on` for the person class (face_embedding is sparse for people
    photographed from behind / partially occluded) so every label re-triggered
    a new run. Count must match what `_collect_examples` would actually train on."""
    person = await session.scalar(select(Class).where(Class.name == "person"))
    sub_a = Subclass(class_id=person.id, name="alice")
    sub_b = Subclass(class_id=person.id, name="bob")
    session.add_all([sub_a, sub_b])
    await session.flush()
    frame = await _seed_frame(session)

    # 100 labeled person detections, none with a face embedding — none of these
    # are usable by the trainer.
    for _ in range(50):
        await _add_labeled_detection(
            session, frame=frame, class_id=person.id, subclass_id=sub_a.id,
            face_embedding=None, object_embedding=[0.1] * 768,
        )
    for _ in range(50):
        await _add_labeled_detection(
            session, frame=frame, class_id=person.id, subclass_id=sub_b.id,
            face_embedding=None, object_embedding=[0.1] * 768,
        )
    await session.commit()

    await maybe_trigger_classifier(session, person.id)
    runs = await session.scalar(
        select(TrainingRun)
        .where(TrainingRun.kind == "classifier", TrainingRun.target_class_id == person.id)
    )
    assert runs is None, "Should not trigger when no rows have face embeddings"


async def test_person_trigger_counts_only_face_embedded_rows(session):  # type: ignore[no-untyped-def]
    """Threshold check should use the face-embedding count, not the raw label count."""
    person = await session.scalar(select(Class).where(Class.name == "person"))
    sub_a = Subclass(class_id=person.id, name="alice")
    sub_b = Subclass(class_id=person.id, name="bob")
    session.add_all([sub_a, sub_b])
    await session.flush()
    frame = await _seed_frame(session)

    # 49 face-embedded labels — below the default threshold of 25 doubled to 50
    # is too easy a target; use 49 against the configured-default 25 to assert
    # the boundary. (Settings default is 25.)
    for i in range(24):
        await _add_labeled_detection(
            session, frame=frame, class_id=person.id,
            subclass_id=sub_a.id if i % 2 == 0 else sub_b.id,
            face_embedding=[0.1] * 512,
        )
    # 100 extra without face embeddings — these used to push the trigger.
    for _ in range(100):
        await _add_labeled_detection(
            session, frame=frame, class_id=person.id, subclass_id=sub_a.id,
            face_embedding=None,
        )
    await session.commit()

    await maybe_trigger_classifier(session, person.id)
    runs = await session.scalar(
        select(TrainingRun)
        .where(TrainingRun.kind == "classifier", TrainingRun.target_class_id == person.id)
    )
    assert runs is None, (
        "24 face-embedded labels is below the threshold; the 100 face-less rows "
        "must not push it over"
    )

    # One more face-embedded label takes us to 25 == threshold.
    await _add_labeled_detection(
        session, frame=frame, class_id=person.id, subclass_id=sub_b.id,
        face_embedding=[0.1] * 512,
    )
    await session.commit()

    await maybe_trigger_classifier(session, person.id)
    run = await session.scalar(
        select(TrainingRun)
        .where(TrainingRun.kind == "classifier", TrainingRun.target_class_id == person.id)
    )
    assert run is not None
    assert run.status == "queued"


async def test_non_person_trigger_uses_object_embedding(session):  # type: ignore[no-untyped-def]
    """For non-person classes, the trainer reads object_embedding — so should the
    trigger. A car row with only face_embedding set should not count."""
    car = await session.scalar(select(Class).where(Class.name == "car"))
    sub_a = Subclass(class_id=car.id, name="sedan")
    sub_b = Subclass(class_id=car.id, name="truck")
    session.add_all([sub_a, sub_b])
    await session.flush()
    frame = await _seed_frame(session)

    # 30 car labels with face_embedding only (nonsensical, but exercises the filter):
    # the trigger should not count these and so should not fire.
    for i in range(30):
        await _add_labeled_detection(
            session, frame=frame, class_id=car.id,
            subclass_id=sub_a.id if i % 2 == 0 else sub_b.id,
            face_embedding=[0.1] * 512, object_embedding=None,
        )
    await session.commit()

    await maybe_trigger_classifier(session, car.id)
    runs = await session.scalar(
        select(TrainingRun)
        .where(TrainingRun.kind == "classifier", TrainingRun.target_class_id == car.id)
    )
    assert runs is None

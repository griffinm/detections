"""Tests for the YOLO dataset builder."""

import uuid

import pytest
from sqlalchemy import select

from vd_db.models import Class, Clip, DetectionModel, Frame, Track
from vd_settings import Settings
from worker.dataset import build_yolo_dataset


async def _seed(session, frames_dir, n_frames, with_jpeg=True):  # type: ignore[no-untyped-def]
    clip = Clip(
        filename="t.mp4", original_path="/in/t.mp4",
        sha256=uuid.uuid4().hex, size_bytes=1, status="done",
    )
    session.add(clip)
    await session.flush()
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    for i in range(n_frames):
        frame = Frame(
            clip_id=clip.id, frame_index=i, timestamp_sec=float(i),
            path=f"{clip.id}/frame_{i:06d}.jpg", width=640, height=480,
            kept=True, detect_status="done",
        )
        session.add(frame)
        await session.flush()
        session.add(
            DetectionModel(
                frame_id=frame.id, class_id=person, predicted_class_id=person,
                bbox={"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
                source="model", reviewed=True, confidence_class=0.9,
            )
        )
        if with_jpeg:
            path = frames_dir / frame.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\xff\xd8\xff")
    await session.commit()


async def test_build_dataset_splits_and_writes_centre_form_labels(session, frames_dir):  # type: ignore[no-untyped-def]
    await _seed(session, frames_dir, n_frames=10)
    manifest = await build_yolo_dataset(session, Settings(), uuid.uuid4())

    assert manifest.counts["train"] == 8
    assert manifest.counts["train"] + manifest.counts["val"] + manifest.counts["test"] == 10
    assert manifest.counts["detections"] == 10
    assert "person" in manifest.class_names
    assert manifest.data_yaml.exists()

    label_files = list((manifest.root / "labels").rglob("*.txt"))
    assert len(label_files) == 10
    person_idx = manifest.class_names.index("person")
    parts = label_files[0].read_text().strip().split()
    assert int(parts[0]) == person_idx
    assert float(parts[1]) == pytest.approx(0.25)  # x + w/2 = 0.1 + 0.3/2
    assert float(parts[2]) == pytest.approx(0.40)  # y + h/2 = 0.2 + 0.4/2


async def test_build_dataset_drops_frames_without_a_jpeg(session, frames_dir):  # type: ignore[no-untyped-def]
    await _seed(session, frames_dir, n_frames=4, with_jpeg=False)
    manifest = await build_yolo_dataset(session, Settings(), uuid.uuid4())
    assert manifest.counts["detections"] == 0
    assert manifest.counts["frames_missing"] == 4


async def test_build_dataset_keeps_one_detection_per_track(session, frames_dir):  # type: ignore[no-untyped-def]
    """A 30-frame walk-through of one tracked object collapses to a single
    YOLO label so the fine-tune loss isn't biased by the over-represented
    track. Loose (track_id=NULL) detections always survive."""
    clip = Clip(
        filename="t.mp4", original_path="/in/t.mp4",
        sha256=uuid.uuid4().hex, size_bytes=1, status="done",
    )
    session.add(clip)
    await session.flush()
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    track = Track(
        clip_id=clip.id, class_id=person, predicted_class_id=person,
        source="tracker", first_frame_index=0, last_frame_index=29,
        n_detections=30, confidence_class=0.9,
    )
    session.add(track)
    await session.flush()
    for i in range(30):
        fr = Frame(
            clip_id=clip.id, frame_index=i, timestamp_sec=float(i),
            path=f"{clip.id}/frame_{i:06d}.jpg", width=640, height=480,
            kept=True, detect_status="done",
        )
        session.add(fr)
        await session.flush()
        session.add(
            DetectionModel(
                frame_id=fr.id, class_id=person, predicted_class_id=person,
                bbox={"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}, source="model",
                reviewed=True, confidence_class=0.5 + i * 0.01,  # ramp so #29 wins
                track_id=track.id,
            )
        )
        path = frames_dir / fr.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xd8\xff")
    # One loose user-drawn detection — always kept.
    loose_frame = Frame(
        clip_id=clip.id, frame_index=30, timestamp_sec=30.0,
        path=f"{clip.id}/frame_000030.jpg", width=640, height=480,
        kept=True, detect_status="done",
    )
    session.add(loose_frame)
    await session.flush()
    session.add(
        DetectionModel(
            frame_id=loose_frame.id, class_id=person,
            bbox={"x": 0.2, "y": 0.2, "w": 0.2, "h": 0.2}, source="user",
            reviewed=True, confidence_class=None,
        )
    )
    loose_path = frames_dir / loose_frame.path
    loose_path.parent.mkdir(parents=True, exist_ok=True)
    loose_path.write_bytes(b"\xff\xd8\xff")
    await session.commit()

    manifest = await build_yolo_dataset(session, Settings(), uuid.uuid4())

    # 30 tracked → 1 rep, plus 1 loose = 2 labels total.
    assert manifest.counts["detections"] == 2
    # The kept tracked frame is whichever had max confidence (i=29).
    label_files = list((manifest.root / "labels").rglob("*.txt"))
    tracked_label_count = sum(
        1 for f in label_files if f.stem != str(loose_frame.id)
    )
    assert tracked_label_count == 1

"""Tests for the YOLO dataset builder."""

import uuid

import pytest
from sqlalchemy import select

from vd_db.models import Class, Clip, DetectionModel, Frame
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

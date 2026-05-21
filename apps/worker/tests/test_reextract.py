"""Integration tests for `vd.reextract_frames`."""

import uuid
from pathlib import Path

from sqlalchemy import select

from vd_db.models import Class, Clip, DetectionAudit, DetectionModel, Frame
from worker.tasks import reextract as reextract_mod
from worker.tasks.reextract import _reextract_frames_async


async def _noop(*args: object, **kwargs: object) -> None:
    return None


async def _seed(session, frames_dir, tmp_path):  # type: ignore[no-untyped-def]
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00")
    clip = Clip(
        filename="v.mp4", original_path="/in/v.mp4", final_path=str(video),
        sha256=uuid.uuid4().hex, size_bytes=1, status="done",
    )
    session.add(clip)
    await session.flush()
    clip_dir = frames_dir / str(clip.id)
    clip_dir.mkdir(parents=True, exist_ok=True)
    (clip_dir / "frame_000000.jpg").write_bytes(b"\xff\xd8\xff")

    frame = Frame(
        clip_id=clip.id, frame_index=0, timestamp_sec=0.0,
        path=f"{clip.id}/frame_000000.jpg", width=10, height=10,
        kept=True, detect_status="done",
    )
    session.add(frame)
    await session.flush()

    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    det = DetectionModel(
        frame_id=frame.id, class_id=person, predicted_class_id=person,
        bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, source="model",
        confidence_class=0.5,
    )
    session.add(det)
    await session.flush()
    session.add(DetectionAudit(
        detection_id=det.id, reason="initial_prediction", to_class_id=person,
    ))
    await session.commit()
    return clip, clip_dir, video, frame, det


async def test_reextract_wipes_frames_and_enqueues_extract(  # type: ignore[no-untyped-def]
    session, frames_dir, tmp_path, monkeypatch,
):
    monkeypatch.setattr(reextract_mod, "publish", _noop)

    calls: list[tuple[str, list[object], str]] = []

    class _FakeCelery:
        def send_task(self, name: str, args: list[object], queue: str) -> None:
            calls.append((name, args, queue))

    monkeypatch.setattr(reextract_mod, "celery_app", _FakeCelery())

    clip, clip_dir, video, frame, det = await _seed(session, frames_dir, tmp_path)

    assert await _reextract_frames_async(str(clip.id)) is True

    # Frame + detection + audit all gone via CASCADE.
    session.expunge_all()
    assert await session.get(Frame, frame.id) is None
    assert await session.get(DetectionModel, det.id) is None
    audits = list(await session.scalars(
        select(DetectionAudit).where(DetectionAudit.detection_id == det.id)
    ))
    assert audits == []

    # Frame directory was wiped; source video is left untouched.
    assert not clip_dir.exists()
    assert video.exists()

    # Clip is queued for re-extraction with status reset.
    refreshed = await session.get(Clip, clip.id)
    assert refreshed is not None
    assert refreshed.status == "extracting"
    assert refreshed.processed_at is None
    assert refreshed.error is None

    assert calls == [("vd.extract_frames", [str(clip.id)], "cpu")]


async def test_reextract_marks_failed_when_source_missing(  # type: ignore[no-untyped-def]
    session, frames_dir, tmp_path, monkeypatch,
):
    """If the source video was removed between API check + worker run, mark
    the clip failed instead of silently wiping its frames."""
    monkeypatch.setattr(reextract_mod, "publish", _noop)

    clip, clip_dir, video, frame, _ = await _seed(session, frames_dir, tmp_path)
    Path(video).unlink()

    assert await _reextract_frames_async(str(clip.id)) is False

    # The worker uses its own session; drop our cache to see what it committed.
    session.expunge_all()
    # Frames are still present — we didn't wipe state we couldn't recover.
    assert await session.get(Frame, frame.id) is not None
    refreshed = await session.get(Clip, clip.id)
    assert refreshed is not None
    assert refreshed.status == "failed"
    assert refreshed.error and "missing" in refreshed.error.lower()


async def test_reextract_missing_clip_is_noop(  # type: ignore[no-untyped-def]
    session, monkeypatch,
):
    monkeypatch.setattr(reextract_mod, "publish", _noop)
    assert await _reextract_frames_async(str(uuid.uuid4())) is False

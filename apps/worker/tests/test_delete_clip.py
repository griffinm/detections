"""Integration tests for `vd.delete_clip`."""

import uuid

from vd_db.models import Clip, Frame
from worker.tasks import delete_clip as delete_clip_mod
from worker.tasks.delete_clip import _delete_clip_async


async def _noop(*args: object, **kwargs: object) -> None:
    return None


async def _seed(session, frames_dir, tmp_path):  # type: ignore[no-untyped-def]
    video = tmp_path / "video.mp4"
    video.write_bytes(b"\x00")
    clip = Clip(
        filename="video.mp4", original_path="/in/video.mp4", final_path=str(video),
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
    await session.commit()
    return clip, clip_dir, video


async def test_delete_clip_removes_row_and_frames(  # type: ignore[no-untyped-def]
    session, frames_dir, tmp_path, monkeypatch
):
    monkeypatch.setattr(delete_clip_mod, "publish", _noop)
    clip, clip_dir, video = await _seed(session, frames_dir, tmp_path)

    assert await _delete_clip_async(str(clip.id)) is True
    session.expunge_all()
    assert await session.get(Clip, clip.id) is None
    assert not clip_dir.exists()
    # delete_processed_videos defaults False — the source video is kept.
    assert video.exists()


async def test_delete_clip_removes_video_when_flag_set(  # type: ignore[no-untyped-def]
    session, frames_dir, tmp_path, monkeypatch
):
    monkeypatch.setenv("VD_DELETE_PROCESSED_VIDEOS", "true")
    monkeypatch.setattr(delete_clip_mod, "publish", _noop)
    clip, clip_dir, video = await _seed(session, frames_dir, tmp_path)

    assert await _delete_clip_async(str(clip.id)) is True
    assert not video.exists()


async def test_delete_missing_clip_is_noop(session, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(delete_clip_mod, "publish", _noop)
    assert await _delete_clip_async(str(uuid.uuid4())) is False

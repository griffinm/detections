"""Integration tests for `vd.prune_frame`."""

import uuid

from vd_db.models import Clip, Frame
from worker.tasks.prune import _prune_frame_async


async def _seed_frame(session, frames_dir, *, kept):  # type: ignore[no-untyped-def]
    clip = Clip(
        filename="t.mp4", original_path="/in/t.mp4",
        sha256=uuid.uuid4().hex, size_bytes=1, status="detecting",
    )
    session.add(clip)
    await session.flush()
    path = f"{clip.id}/frame_000000.jpg"
    frame = Frame(
        clip_id=clip.id, frame_index=0, timestamp_sec=0.0, path=path,
        width=640, height=480, kept=kept, detect_status="done",
    )
    session.add(frame)
    await session.commit()
    file_path = frames_dir / path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"\xff\xd8\xff")
    return frame, file_path


async def test_prune_deletes_deduped_frame(session, frames_dir):  # type: ignore[no-untyped-def]
    frame, file_path = await _seed_frame(session, frames_dir, kept=False)

    assert await _prune_frame_async(str(frame.id)) is True
    assert not file_path.exists()

    await session.refresh(frame)
    assert frame.path is None


async def test_prune_skips_kept_frame(session, frames_dir):  # type: ignore[no-untyped-def]
    frame, file_path = await _seed_frame(session, frames_dir, kept=True)

    assert await _prune_frame_async(str(frame.id)) is False
    assert file_path.exists()

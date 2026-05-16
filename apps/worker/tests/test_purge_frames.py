"""Integration tests for `vd.purge_frames`."""

import uuid
from datetime import UTC, datetime, timedelta

from vd_db.models import Clip, Frame
from worker.tasks.purge import _purge_frames_async


async def _seed(session, frames_dir, *, age_days):  # type: ignore[no-untyped-def]
    clip = Clip(
        filename="t.mp4", original_path="/in/t.mp4",
        sha256=uuid.uuid4().hex, size_bytes=1, status="done",
        created_at=datetime.now(UTC) - timedelta(days=age_days),
    )
    session.add(clip)
    await session.flush()
    path = f"{clip.id}/frame_000000.jpg"
    frame = Frame(
        clip_id=clip.id, frame_index=0, timestamp_sec=0.0, path=path,
        width=10, height=10, kept=True, detect_status="done",
    )
    session.add(frame)
    await session.commit()
    file_path = frames_dir / path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"\xff\xd8\xff")
    return frame, file_path


async def test_purge_removes_only_old_frames(session, frames_dir):  # type: ignore[no-untyped-def]
    old_frame, old_file = await _seed(session, frames_dir, age_days=60)
    new_frame, new_file = await _seed(session, frames_dir, age_days=1)

    assert await _purge_frames_async(30) == 1
    assert not old_file.exists()
    assert new_file.exists()

    await session.refresh(old_frame)
    await session.refresh(new_frame)
    assert old_frame.path is None
    assert new_frame.path is not None

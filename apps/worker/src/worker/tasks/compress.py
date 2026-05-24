"""`vd.compress_video` — re-encode `clip.final_path` to HEVC via NVENC.

Idempotent via `clip.codec`: skipped when already `'hevc'`. The replace
is atomic (`.compress.tmp.<ext>` sibling then `os.replace`); a missing
source or ffmpeg failure leaves the original untouched.
"""

import asyncio
import os
import uuid
from pathlib import Path

from vd_db import load_effective_settings
from vd_db.models import Clip
from vd_tasks.app import celery_app

from worker.db import db_session
from worker.events import publish


async def _compress_video_async(clip_id: str) -> bool:
    cid = uuid.UUID(clip_id)

    async with db_session() as session:
        settings = await load_effective_settings(session)
        clip = await session.get(Clip, cid)
        if clip is None or not clip.final_path:
            return False
        # Skip natively-HEVC and previously-compressed clips so retries
        # and `vd.reextract_frames` re-runs converge to a no-op.
        if (clip.codec or "").lower() in {"hevc", "h265"}:
            return False
        final_path = Path(clip.final_path)
        crf = settings.compress_crf

    if not final_path.exists():
        return False

    size_before = final_path.stat().st_size
    # Keep the original suffix on the tmp file so ffmpeg picks the right
    # container muxer from the extension (a literal `.tmp` would fail).
    tmp_path = final_path.with_name(
        f"{final_path.stem}.compress.tmp{final_path.suffix}"
    )

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-nostdin", "-y",
        "-i", str(final_path),
        "-c:v", "hevc_nvenc", "-preset", "p5",
        "-rc", "vbr", "-cq", str(crf), "-b:v", "0",
        "-c:a", "copy",
        str(tmp_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"hevc_nvenc exited {proc.returncode}: {stderr.decode()[-500:]}"
        )

    os.replace(tmp_path, final_path)
    size_after = final_path.stat().st_size

    async with db_session() as session:
        clip = await session.get(Clip, cid)
        if clip is not None:
            clip.codec = "hevc"
            clip.size_bytes = size_after
            await session.commit()

    await publish(
        "clip.compressed",
        clip_id=clip_id,
        size_before=size_before,
        size_after=size_after,
    )
    return True


@celery_app.task(name="vd.compress_video", bind=True, max_retries=3)
def compress_video(self, clip_id: str) -> bool:  # type: ignore[misc]
    try:
        return asyncio.run(_compress_video_async(clip_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10) from exc

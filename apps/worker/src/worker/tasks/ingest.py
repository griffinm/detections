import asyncio
import hashlib
import json
import logging
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from vd_db.models import Clip
from vd_settings import Settings
from vd_tasks.app import celery_app

from worker.db import db_session
from worker.events import publish

logger = logging.getLogger(__name__)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _place_file(src: Path, dest: Path) -> None:
    """Move `src` to `dest`, idempotently — a no-op if `dest` already exists.

    Safe to call after a partial prior attempt: the move is the last step of
    ingest, so `dest` existing means a previous run already completed it.
    """
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))


async def _ingest_video_async(clip_path: str) -> str:
    path = Path(clip_path)
    settings = Settings()

    if not path.exists():
        # The source already left the inbox. Since the file move is ingest's
        # final step, a prior attempt must have run to completion — nothing
        # left to do, and a retry here would otherwise fail on a missing file.
        logger.info("ingest: %s already processed, skipping", clip_path)
        return ""

    sha = _sha256(path)

    async with db_session() as session:
        existing = await session.scalar(select(Clip).where(Clip.sha256 == sha))
        if existing is not None:
            clip_id = existing.id
            dest = (
                Path(existing.final_path)
                if existing.final_path
                else settings.processed_dir / str(clip_id) / path.name
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_streams", "-show_format", str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            meta: dict = json.loads(stdout)

            video_stream = next(
                (s for s in meta.get("streams", []) if s.get("codec_type") == "video"),
                None,
            )
            fmt = meta.get("format", {})

            raw_dur = fmt.get("duration")
            duration_sec = float(raw_dur) if raw_dur else None
            fps: float | None = None
            width: int | None = None
            height: int | None = None
            codec: str | None = None

            if video_stream:
                codec = video_stream.get("codec_name")
                width = video_stream.get("width")
                height = video_stream.get("height")
                avg_fr = video_stream.get("avg_frame_rate", "0/1")
                try:
                    num_s, den_s = avg_fr.split("/")
                    num, den = float(num_s), float(den_s)
                    fps = num / den if den else None
                except (ValueError, ZeroDivisionError):
                    fps = None

            clip = Clip(
                filename=path.name,
                original_path=str(path),
                sha256=sha,
                size_bytes=path.stat().st_size,
                duration_sec=duration_sec,
                fps=fps,
                width=width,
                height=height,
                codec=codec,
                status="extracting",
                ingested_at=datetime.now(UTC),
            )
            session.add(clip)
            await session.flush()
            clip_id = clip.id
            dest = settings.processed_dir / str(clip_id) / path.name
            clip.final_path = str(dest)
            await session.commit()

    # Tail steps, all idempotent. The file move is intentionally LAST: once the
    # source has left the inbox every preceding step has succeeded, so a retry
    # either re-runs cleanly (file still in inbox) or short-circuits at the
    # not-exists guard above. Moving before the commit could strand the video
    # under a UUID directory with no `clips` row if the commit failed.
    celery_app.send_task("vd.extract_frames", args=[str(clip_id)], queue="cpu")
    await publish("clip.status", clip_id=str(clip_id), status="extracting")
    _place_file(path, dest)
    return str(clip_id)


def _quarantine(clip_path: str) -> None:
    """Move a permanently-failed source video to `failed/` so the inbox watcher
    stops re-triggering ingest on it."""
    src = Path(clip_path)
    if not src.exists():
        return
    failed_dir = Settings().failed_dir
    try:
        failed_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(failed_dir / src.name))
        logger.error("ingest: quarantined %s to %s", src.name, failed_dir)
    except OSError:
        logger.exception("ingest: failed to quarantine %s", clip_path)


@celery_app.task(name="vd.ingest_video", bind=True, max_retries=3)
def ingest_video(self, clip_path: str) -> str:  # type: ignore[misc]
    try:
        return asyncio.run(_ingest_video_async(clip_path))
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=5) from exc
        # Retries exhausted: quarantine the file so it doesn't loop forever.
        _quarantine(clip_path)
        raise

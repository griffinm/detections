import asyncio
import hashlib
import json
import logging
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def _probe_metadata(path: Path) -> dict[str, object]:
    """ffprobe a video into `{duration_sec, fps, width, height, codec}`."""
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
    raw_dur = meta.get("format", {}).get("duration")
    out: dict[str, object] = {
        "duration_sec": float(raw_dur) if raw_dur else None,
        "fps": None,
        "width": None,
        "height": None,
        "codec": None,
    }
    if video_stream:
        out["codec"] = video_stream.get("codec_name")
        out["width"] = video_stream.get("width")
        out["height"] = video_stream.get("height")
        avg_fr = video_stream.get("avg_frame_rate", "0/1")
        try:
            num_s, den_s = avg_fr.split("/")
            num, den = float(num_s), float(den_s)
            out["fps"] = num / den if den else None
        except (ValueError, ZeroDivisionError):
            out["fps"] = None
    return out


async def _dedup_job_onto(
    session: AsyncSession, settings: Settings, path: Path, clip_id: str, existing: Clip
) -> str:
    """A job submission (`clip_id`) carries bytes identical to `existing` —
    link the API-created row to that canonical clip instead of re-extracting.

    The job result and callback resolve through `canonical_clip_id`; if the
    canonical clip is still in flight its completion handler fans the callback
    out, so this only fires the callback itself when it has already finished.
    """
    job_clip = await session.get(Clip, uuid.UUID(clip_id))
    dest = settings.processed_dir / clip_id / path.name
    callback_url: str | None = None
    if job_clip is not None:
        job_clip.canonical_clip_id = existing.id
        job_clip.final_path = str(dest)
        callback_url = job_clip.callback_url
        if existing.status in ("done", "failed"):
            job_clip.status = existing.status
        await session.commit()

    _place_file(path, dest)
    if callback_url and existing.status in ("done", "failed"):
        celery_app.send_task(
            "vd.deliver_callback",
            args=[clip_id, f"clip.{existing.status}"],
            queue="cpu",
        )
    logger.info("ingest: job %s deduped onto canonical clip %s", clip_id, existing.id)
    return clip_id


async def _ingest_video_async(clip_path: str, clip_id: str | None = None) -> str:
    """Ingest a video. The folder watcher passes only `clip_path`; a
    `POST /api/jobs` submission passes `clip_id` too — the API already created
    the `clips` row, so this run fills in the hash + ffprobe metadata."""
    path = Path(clip_path)
    settings = Settings()

    if not path.exists():
        # The source already left its drop directory. Since the file move is
        # ingest's final step, a prior attempt ran to completion — nothing to
        # do, and a retry would otherwise fail on the missing file.
        logger.info("ingest: %s already processed, skipping", clip_path)
        return clip_id or ""

    sha = _sha256(path)

    async with db_session() as session:
        existing = await session.scalar(select(Clip).where(Clip.sha256 == sha))

        if existing is not None:
            # This content is already ingested.
            if clip_id is None:
                # Watcher drop of a duplicate file — discard to processed/.
                dest = (
                    Path(existing.final_path)
                    if existing.final_path
                    else settings.processed_dir / str(existing.id) / path.name
                )
                _place_file(path, dest)
                logger.info(
                    "ingest: %s already ingested as %s", clip_path, existing.id
                )
                return str(existing.id)
            return await _dedup_job_onto(session, settings, path, clip_id, existing)

        # New content.
        meta = await _probe_metadata(path)
        if clip_id is None:
            clip = Clip(
                filename=path.name,
                original_path=str(path),
                sha256=sha,
                size_bytes=path.stat().st_size,
                status="extracting",
                ingested_at=datetime.now(UTC),
                **meta,
            )
            session.add(clip)
            await session.flush()
        else:
            clip = await session.get(Clip, uuid.UUID(clip_id))
            if clip is None:
                # Defensive: the API normally created this row up front.
                clip = Clip(
                    id=uuid.UUID(clip_id),
                    filename=path.name,
                    original_path=str(path),
                    size_bytes=path.stat().st_size,
                )
                session.add(clip)
            clip.sha256 = sha
            clip.status = "extracting"
            clip.ingested_at = datetime.now(UTC)
            clip.duration_sec = meta["duration_sec"]
            clip.fps = meta["fps"]
            clip.width = meta["width"]
            clip.height = meta["height"]
            clip.codec = meta["codec"]

        clip_uuid = clip.id
        dest = settings.processed_dir / str(clip_uuid) / path.name
        clip.final_path = str(dest)
        await session.commit()

    # Tail steps, all idempotent. The file move is intentionally LAST: once the
    # source has left its drop directory every preceding step has succeeded, so
    # a retry either re-runs cleanly (file still present) or short-circuits at
    # the not-exists guard above.
    celery_app.send_task("vd.extract_frames", args=[str(clip_uuid)], queue="cpu")
    await publish("clip.status", clip_id=str(clip_uuid), status="extracting")
    _place_file(path, dest)
    return str(clip_uuid)


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


async def _mark_job_failed(clip_id: str, error: str) -> None:
    """Record a permanent ingest failure on a job's `clips` row and notify the
    submitter. Watcher drops have no row yet, so this runs for jobs only."""
    async with db_session() as session:
        clip = await session.get(Clip, uuid.UUID(clip_id))
        if clip is None:
            return
        clip.status = "failed"
        clip.error = error
        callback_url = clip.callback_url
        await session.commit()
    if callback_url:
        celery_app.send_task(
            "vd.deliver_callback", args=[clip_id, "clip.failed"], queue="cpu"
        )


@celery_app.task(name="vd.ingest_video", bind=True, max_retries=3)
def ingest_video(  # type: ignore[misc]
    self, clip_path: str, clip_id: str | None = None
) -> str:
    try:
        return asyncio.run(_ingest_video_async(clip_path, clip_id))
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=5) from exc
        # Retries exhausted: quarantine the file so it doesn't loop forever.
        _quarantine(clip_path)
        # A job submission already has a `clips` row — mark it failed + notify.
        if clip_id is not None:
            asyncio.run(_mark_job_failed(clip_id, str(exc)))
        raise

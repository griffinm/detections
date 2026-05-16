import asyncio
import hashlib
import json
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


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


async def _ingest_video_async(clip_path: str) -> str:
    path = Path(clip_path)
    settings = Settings()

    sha = _sha256(path)

    async with db_session() as session:
        existing = await session.scalar(select(Clip).where(Clip.sha256 == sha))
        if existing is not None:
            return str(existing.id)

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
        clip_id: uuid.UUID = clip.id

        dest_dir = settings.processed_dir / str(clip_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / path.name
        shutil.move(str(path), str(dest))

        clip.final_path = str(dest)
        await session.commit()

    await publish("clip.status", clip_id=str(clip_id), status="extracting")
    celery_app.send_task("vd.extract_frames", args=[str(clip_id)], queue="cpu")
    return str(clip_id)


@celery_app.task(name="vd.ingest_video", bind=True, max_retries=3)
def ingest_video(self, clip_path: str) -> str:  # type: ignore[misc]
    try:
        return asyncio.run(_ingest_video_async(clip_path))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=5) from exc

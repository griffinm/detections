import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from vd_db import load_effective_settings
from vd_db.base import _uuid7
from vd_db.models import Clip, Frame
from vd_tasks.app import celery_app

from worker.db import db_session
from worker.events import publish


async def _extract_frames_async(clip_id: str) -> int:
    cid = uuid.UUID(clip_id)

    async with db_session() as session:
        settings = await load_effective_settings(session)
        clip = await session.get(Clip, cid)
        if clip is None or clip.status != "extracting":
            return 0

        frames_dir = settings.frames_dir / clip_id
        frames_dir.mkdir(parents=True, exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-i", str(clip.final_path),
            "-vf", f"fps={settings.frame_fps}",
            "-q:v", str(settings.frame_jpeg_quality // 10),
            "-start_number", "0",
            str(frames_dir / "frame_%06d.jpg"),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg exited {proc.returncode}: {stderr.decode()[-500:]}")

        frame_files = sorted(frames_dir.glob("frame_*.jpg"))
        frame_count = len(frame_files)

        for batch_start in range(0, frame_count, 100):
            batch = frame_files[batch_start: batch_start + 100]
            for frame_file in batch:
                idx = int(frame_file.stem.split("_")[1])
                timestamp = idx / settings.frame_fps
                rel_path = f"{clip_id}/frame_{idx:06d}.jpg"

                stmt = pg_insert(Frame).values(
                    id=_uuid7(),
                    clip_id=cid,
                    frame_index=idx,
                    timestamp_sec=timestamp,
                    path=rel_path,
                    width=clip.width or 0,
                    height=clip.height or 0,
                    kept=True,
                    detect_status="pending",
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["clip_id", "frame_index"],
                    set_={
                        "path": stmt.excluded.path,
                        "timestamp_sec": stmt.excluded.timestamp_sec,
                        "updated_at": datetime.now(UTC),
                    },
                )
                await session.execute(stmt)
            await session.commit()

        # Schedule detection in gpu-queue batches; completion is reported by
        # vd.detect_frame_batch once every frame of the clip is detected.
        kept_ids = list(
            await session.scalars(
                select(Frame.id).where(Frame.clip_id == cid, Frame.kept.is_(True))
            )
        )
        for start in range(0, len(kept_ids), settings.detect_batch_size):
            chunk = [str(fid) for fid in kept_ids[start: start + settings.detect_batch_size]]
            celery_app.send_task("vd.detect_frame_batch", args=[chunk], queue="gpu")

        clip = await session.get(Clip, cid)
        if clip is not None:
            clip.status = "done" if not kept_ids else "detecting"
            clip.processed_at = datetime.now(UTC)
            await session.commit()

    status = "done" if not kept_ids else "detecting"
    await publish("clip.status", clip_id=clip_id, status=status)
    if status == "done":
        await publish("clip.done", clip_id=clip_id)
    return frame_count


@celery_app.task(name="vd.extract_frames", bind=True, max_retries=3)
def extract_frames(self, clip_id: str) -> int:  # type: ignore[misc]
    try:
        return asyncio.run(_extract_frames_async(clip_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10) from exc

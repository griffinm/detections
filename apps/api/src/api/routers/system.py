import asyncio
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ..deps import enqueue, get_db, get_redis, settings
from ..schemas.metrics import HealthResponse
from ..schemas.system import (
    DirUsage,
    DiskUsageResponse,
    PurgeRequest,
    PurgeResponse,
    TracksBackfillRequest,
    TracksBackfillResponse,
    TracksBackfillStatus,
)
from vd_db.models import Clip, DetectionModel, Frame, Track

router = APIRouter(tags=["system"])


@router.get("/system/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    db_status = "error"
    redis_status = "error"

    try:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        db_status = "ok"
    except Exception:
        pass

    try:
        r = get_redis()
        await r.ping()  # type: ignore[misc]
        await r.aclose()
        redis_status = "ok"
    except Exception:
        pass

    return HealthResponse(db=db_status, redis=redis_status)


def _dir_usage(path: Path) -> tuple[int, int]:
    """Total bytes and file count under `path` (recursive, symlinks not followed)."""
    total = 0
    count = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        count += 1
                        total += entry.stat(follow_symlinks=False).st_size
        except OSError:
            continue
    return total, count


def _collect_disk_usage() -> DiskUsageResponse:
    named_dirs = [
        ("inbox", settings.inbox_dir),
        ("processed", settings.processed_dir),
        ("frames", settings.frames_dir),
        ("models", settings.models_dir),
    ]
    dirs: list[DirUsage] = []
    for name, path in named_dirs:
        size, count = _dir_usage(path)
        dirs.append(DirUsage(name=name, path=str(path), bytes=size, file_count=count))

    # disk_usage needs an existing path — walk up to the first real ancestor.
    probe = settings.frames_dir
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    return DiskUsageResponse(dirs=dirs, total_bytes=usage.total, free_bytes=usage.free)


@router.get("/system/disk", response_model=DiskUsageResponse)
async def disk_usage() -> DiskUsageResponse:
    # Filesystem walk is blocking — keep it off the event loop.
    return await asyncio.to_thread(_collect_disk_usage)


@router.post("/system/purge-frames", response_model=PurgeResponse, status_code=202)
async def purge_frames(body: PurgeRequest) -> PurgeResponse:
    enqueue("vd.purge_frames", body.older_than_days, queue="cpu")
    return PurgeResponse(enqueued=True, older_than_days=body.older_than_days)


@router.get("/system/backfill-tracks", response_model=TracksBackfillStatus)
async def backfill_tracks_status(
    db: AsyncSession = Depends(get_db),
) -> TracksBackfillStatus:
    """How many clips have detections but no tracks (Phase-9 backfill backlog)."""
    detected = (
        select(Frame.clip_id)
        .join(DetectionModel, DetectionModel.frame_id == Frame.id)
        .where(DetectionModel.deleted_at.is_(None))
        .distinct()
    )
    tracked = select(Track.clip_id).where(Track.deleted_at.is_(None)).distinct()
    eligible = await db.scalar(
        select(func.count())
        .select_from(Clip)
        .where(Clip.id.in_(detected), Clip.id.notin_(tracked))
    )
    return TracksBackfillStatus(eligible_clips=int(eligible or 0))


@router.post(
    "/system/backfill-tracks", response_model=TracksBackfillResponse, status_code=202
)
async def backfill_tracks_sweep(body: TracksBackfillRequest) -> TracksBackfillResponse:
    """Sweep up to `limit` pre-Phase-9 clips into the tracking pipeline."""
    enqueue("vd.backfill_tracks", None, body.limit, queue="cpu")
    return TracksBackfillResponse(enqueued=True, limit=body.limit)

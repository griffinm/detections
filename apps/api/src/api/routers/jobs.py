"""External integration API — submit a video, get back who/what is in it.

The app-to-app surface for the upstream apps (UniFi Protect motion archiver,
family-video archiver). They share the host filesystem, so a video is passed by
path reference: the app writes it under `VD_INTAKE_DIR`, then calls this. The
job *is* the clip — `job_id == clip_id`, there is no separate jobs table.
"""

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import enqueue, get_db, settings
from api.schemas.job import JobAccepted, JobCreate
from vd_db import build_job_result
from vd_db.models import Clip

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", status_code=202, response_model=JobAccepted)
async def create_job(
    body: JobCreate, db: AsyncSession = Depends(get_db)
) -> JobAccepted:
    """Submit a video already written under `VD_INTAKE_DIR`.

    Returns 202 immediately — processing is async. The clip runs the same
    pipeline as a watched-folder drop; the result is delivered to
    `callback_url` (if given) and is also available from `GET /api/jobs/{id}`.
    """
    intake = settings.intake_dir.resolve()
    try:
        video = Path(body.video_path).resolve(strict=True)
    except (OSError, RuntimeError):
        # Missing file, broken symlink, or a symlink loop.
        raise HTTPException(422, "video_path does not exist") from None
    # `resolve` has already collapsed any `..` / symlink escape — a path that
    # still is not under the intake root is rejected.
    if not video.is_relative_to(intake):
        raise HTTPException(
            422, f"video_path must be inside the intake directory ({intake})"
        )
    if not video.is_file():
        raise HTTPException(422, "video_path is not a file")

    # Idempotent on (source, external_id): a re-submit returns the existing job
    # rather than creating a duplicate clip.
    if body.external_id is not None:
        existing = await db.scalar(
            select(Clip).where(
                Clip.source == body.source,
                Clip.external_id == body.external_id,
            )
        )
        if existing is not None:
            return JobAccepted(job_id=existing.id, status=existing.status)

    clip = Clip(
        filename=video.name,
        original_path=str(video),
        size_bytes=video.stat().st_size,
        status="pending",
        source=body.source,
        external_id=body.external_id,
        callback_url=str(body.callback_url) if body.callback_url else None,
        external_metadata=body.metadata,
    )
    db.add(clip)
    await db.commit()
    await db.refresh(clip)

    # The worker hashes the file, ffprobes it, and fills in the row.
    enqueue("vd.ingest_video", str(video), str(clip.id), queue="cpu")
    return JobAccepted(job_id=clip.id, status="pending")


@router.get("/{job_id}")
async def get_job(
    job_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Job status + result. While in flight only `status` is populated; once
    terminal the body carries the full detection result (spec 04 §Jobs)."""
    clip = await db.get(Clip, job_id)
    if clip is None:
        raise HTTPException(404, "Job not found")
    return await build_job_result(db, clip)

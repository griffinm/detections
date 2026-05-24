import os
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import enqueue, get_db, settings
from api.schemas.clip import (
    ClipClassSummary,
    ClipDetail,
    ClipDetectionGroup,
    ClipRead,
)
from api.schemas.common import Paginated
from api.schemas.detection import DetectionGalleryItem
from api.schemas.frame import FrameRead
from api.services.gallery import GalleryInclude, query_gallery_items
from vd_db.models import Class, Clip, DetectionModel, Frame, Subclass

router = APIRouter(prefix="/clips", tags=["clips"])

# Kept in sync with the ingest-watcher's VIDEO_EXTENSIONS.
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm"}
_UPLOAD_CHUNK = 1 << 20  # 1 MiB


@router.get("", response_model=Paginated[ClipRead])
async def list_clips(
    page: int = 1,
    page_size: int = 50,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> Paginated[ClipRead]:
    q = select(Clip).order_by(Clip.created_at.desc())
    if status:
        q = q.where(Clip.status == status)

    total = await db.scalar(select(func.count()).select_from(q.subquery()))
    rows = list(await db.scalars(q.offset((page - 1) * page_size).limit(page_size)))

    # One representative thumbnail per clip: the lowest-indexed kept frame that
    # still has a JPEG on disk (object-free frames get pruned).
    thumbs: dict[uuid.UUID, str] = {}
    summaries: dict[uuid.UUID, list[ClipDetectionGroup]] = {}
    if rows:
        clip_ids = [c.id for c in rows]
        frame_rows = await db.execute(
            select(Frame.clip_id, Frame.path)
            .distinct(Frame.clip_id)
            .where(
                Frame.clip_id.in_(clip_ids),
                Frame.kept.is_(True),
                Frame.path.is_not(None),
            )
            .order_by(Frame.clip_id, Frame.frame_index)
        )
        thumbs = {cid: f"/files/frames/{path}" for cid, path in frame_rows}

        # One GROUP BY across every clip on the page — avoids N per-clip
        # summary fetches from the frontend. Ordered so the dominant
        # (class, sub-class) bucket lands first inside each clip.
        group_rows = await db.execute(
            select(
                Frame.clip_id,
                DetectionModel.class_id,
                Class.name.label("class_name"),
                Class.color_hex.label("class_color"),
                DetectionModel.subclass_id,
                Subclass.name.label("subclass_name"),
                Subclass.color_hex.label("subclass_color"),
                func.count().label("n"),
            )
            .select_from(DetectionModel)
            .join(Frame, Frame.id == DetectionModel.frame_id)
            .outerjoin(Class, Class.id == DetectionModel.class_id)
            .outerjoin(Subclass, Subclass.id == DetectionModel.subclass_id)
            .where(
                Frame.clip_id.in_(clip_ids),
                DetectionModel.deleted_at.is_(None),
            )
            .group_by(
                Frame.clip_id,
                DetectionModel.class_id,
                Class.name,
                Class.color_hex,
                DetectionModel.subclass_id,
                Subclass.name,
                Subclass.color_hex,
            )
            .order_by(Frame.clip_id, func.count().desc())
        )
        for (
            clip_id,
            class_id,
            class_name,
            class_color,
            subclass_id,
            subclass_name,
            subclass_color,
            n,
        ) in group_rows:
            summaries.setdefault(clip_id, []).append(
                ClipDetectionGroup(
                    class_id=class_id,
                    class_name=class_name,
                    class_color=class_color,
                    subclass_id=subclass_id,
                    subclass_name=subclass_name,
                    subclass_color=subclass_color,
                    count=n,
                )
            )

    items = [
        ClipRead.model_validate(c).model_copy(
            update={
                "thumbnail_url": thumbs.get(c.id),
                "detection_summary": summaries.get(c.id, []),
            }
        )
        for c in rows
    ]
    return Paginated(items=items, total=total or 0)


@router.post("/upload", status_code=202)
async def upload_clip(file: UploadFile) -> dict[str, object]:
    """Accept a browser video upload and drop it into the watched inbox.

    The file lands in `VD_INBOX_DIR` exactly like a manual drop — the
    ingest-watcher then enqueues `vd.ingest_video`. The API deliberately
    creates no `clips` row and enqueues nothing itself: doing so would race the
    watcher into a duplicate, metadata-less row (see spec 02 §External video
    submission, which is why `intake/` is unwatched and `inbox/` is not).

    The bytes stream to a hidden `.part` file, then get atomically renamed to
    the final video name. The watcher ignores the `.part` file (non-video
    suffix) and picks the finished video up via its `on_moved` handler, so it
    never sees a half-written file.

    Declared before `/{clip_id}` so the literal path wins the route match.
    """
    raw = Path(file.filename or "upload")
    ext = raw.suffix.lower()
    if ext not in VIDEO_EXTENSIONS:
        raise HTTPException(
            415,
            f"Unsupported file type '{ext or raw.name}'. "
            f"Allowed: {', '.join(sorted(VIDEO_EXTENSIONS))}",
        )

    inbox = settings.inbox_dir
    inbox.mkdir(parents=True, exist_ok=True)
    # Collapse the upload name to a bare, filesystem-safe stem — no directory
    # component from the client can escape the inbox.
    stem = re.sub(r"[^\w.\- ]+", "_", raw.stem).strip() or "upload"

    part = inbox / f".upload-{uuid.uuid4().hex}{ext}.part"
    size = 0
    try:
        with part.open("wb") as out:
            while chunk := await file.read(_UPLOAD_CHUNK):
                out.write(chunk)
                size += len(chunk)
        if size == 0:
            raise HTTPException(422, "Uploaded file is empty")
        final = inbox / f"{stem}{ext}"
        n = 1
        while final.exists():
            final = inbox / f"{stem}-{n}{ext}"
            n += 1
        os.replace(part, final)
    except BaseException:
        # Never leave a stray file behind; the `.part` name keeps a failed
        # upload invisible to the watcher in the first place.
        part.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    return {"filename": final.name, "size_bytes": size}


@router.get("/{clip_id}", response_model=ClipDetail)
async def get_clip(
    clip_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ClipDetail:
    clip = await db.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")

    frame_count = await db.scalar(
        select(func.count()).where(Frame.clip_id == clip_id)
    )
    data = ClipRead.model_validate(clip).model_dump()
    return ClipDetail(**data, frame_count=frame_count or 0)


@router.delete("/{clip_id}", status_code=202)
async def delete_clip(
    clip_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Enqueue clip removal: the worker drops frame JPEGs (and the video, if
    `delete_processed_videos`) then deletes the row, cascading frames +
    detections. The UI removes the clip on the `clip.deleted` SSE event."""
    clip = await db.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    enqueue("vd.delete_clip", str(clip_id), queue="cpu")
    return {"enqueued": True, "clip_id": str(clip_id)}


@router.post("/{clip_id}/reextract", status_code=202)
async def reextract_clip(
    clip_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Wipe this clip's frames + detections and re-run extraction + detection.

    Needs the source video still on disk — `delete_processed_videos` setups
    that lose the bytes after ingest can't re-extract. The clip's status
    flips back to `extracting`; the SSE event train (`clip.status` →
    `clip.done`) drives the UI updates exactly like a fresh ingest.
    """
    clip = await db.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    if clip.final_path is None or not Path(clip.final_path).exists():
        raise HTTPException(
            status_code=409,
            detail="Source video is no longer on disk — cannot re-extract.",
        )
    enqueue("vd.reextract_frames", str(clip_id), queue="cpu")
    return {"enqueued": True, "clip_id": str(clip_id)}


@router.get("/{clip_id}/frames", response_model=list[FrameRead])
async def list_frames(
    clip_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[FrameRead]:
    clip = await db.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")

    rows = await db.scalars(
        select(Frame)
        .where(Frame.clip_id == clip_id, Frame.kept.is_(True))
        .order_by(Frame.frame_index)
    )
    return [
        FrameRead.model_validate(f).model_copy(
            update={"image_url": f"/files/frames/{f.path}" if f.path else None}
        )
        for f in rows
    ]


@router.get("/{clip_id}/detections", response_model=list[DetectionGalleryItem])
async def list_clip_detections(
    clip_id: uuid.UUID,
    class_id: uuid.UUID | None = Query(default=None),
    subclass_id: uuid.UUID | None = Query(default=None),
    include: GalleryInclude = Query(default="all"),
    limit: int = Query(default=500, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
) -> list[DetectionGalleryItem]:
    """Every non-deleted detection on this clip, ordered by frame index.

    Powers the bulk-label-by-clip view. The class filter is the main lever —
    a clip is normally many frames of one subject, so 'all person crops in
    this clip' is the natural unit to bulk-confirm.
    """
    clip = await db.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")

    conditions: list[object] = [Frame.clip_id == clip_id]
    if class_id is not None:
        conditions.append(DetectionModel.class_id == class_id)
    if subclass_id is not None:
        conditions.append(DetectionModel.subclass_id == subclass_id)

    return await query_gallery_items(
        db,
        where=and_(*conditions),
        include=include,
        sort="frame_asc",
        limit=limit,
    )


@router.get("/{clip_id}/class-summary", response_model=list[ClipClassSummary])
async def get_clip_class_summary(
    clip_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[ClipClassSummary]:
    """Per-class detection counts for this clip — the bulk-label page picks
    the most-common class as the default filter."""
    clip = await db.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="Clip not found")

    rows = await db.execute(
        select(
            DetectionModel.class_id,
            Class.name.label("class_name"),
            func.count().label("n"),
        )
        .select_from(DetectionModel)
        .join(Frame, Frame.id == DetectionModel.frame_id)
        .outerjoin(Class, Class.id == DetectionModel.class_id)
        .where(Frame.clip_id == clip_id, DetectionModel.deleted_at.is_(None))
        .group_by(DetectionModel.class_id, Class.name)
        .order_by(func.count().desc())
    )
    return [
        ClipClassSummary(class_id=cid, class_name=name, count=n)
        for cid, name, n in rows
    ]

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import enqueue, get_db
from api.schemas.clip import ClipDetail, ClipRead
from api.schemas.common import Paginated
from api.schemas.frame import FrameRead
from vd_db.models import Clip, Frame

router = APIRouter(prefix="/clips", tags=["clips"])


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
    if rows:
        frame_rows = await db.execute(
            select(Frame.clip_id, Frame.path)
            .distinct(Frame.clip_id)
            .where(
                Frame.clip_id.in_([c.id for c in rows]),
                Frame.kept.is_(True),
                Frame.path.is_not(None),
            )
            .order_by(Frame.clip_id, Frame.frame_index)
        )
        thumbs = {cid: f"/files/frames/{path}" for cid, path in frame_rows}

    items = [
        ClipRead.model_validate(c).model_copy(update={"thumbnail_url": thumbs.get(c.id)})
        for c in rows
    ]
    return Paginated(items=items, total=total or 0)


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

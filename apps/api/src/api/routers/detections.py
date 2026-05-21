"""Detection CRUD — the write path for the labeling UI.

Every classification action (reassign / review / delete / user-drawn box) is
recorded in the insert-only `detection_audits` ledger. Pure geometry edits
(move / resize) update `bbox` only — the audit table has no geometry columns.
Deletes are soft (`deleted_at`) so the `user_delete` audit survives the
`ON DELETE CASCADE` ledger FK.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import enqueue, get_db
from api.schemas.detection import (
    DetectionCreate,
    DetectionRead,
    DetectionUpdate,
    PromoteExample,
)
from api.services.crops import ensure_crop
from api.services.events import publish
from api.services.training_service import maybe_trigger_training
from vd_db.models import Class, DetectionAudit, DetectionModel, Frame, Subclass, SubclassExample

router = APIRouter(prefix="/detections", tags=["detections"])


def _audit(
    detection: DetectionModel,
    *,
    reason: str,
    from_class_id: uuid.UUID | None = None,
    to_class_id: uuid.UUID | None = None,
    from_subclass_id: uuid.UUID | None = None,
    to_subclass_id: uuid.UUID | None = None,
) -> DetectionAudit:
    return DetectionAudit(
        detection_id=detection.id,
        reason=reason,
        from_class_id=from_class_id,
        to_class_id=to_class_id,
        from_subclass_id=from_subclass_id,
        to_subclass_id=to_subclass_id,
        model_version_id=detection.model_version_id,
    )


async def _publish_frame_updated(db: AsyncSession, frame_id: uuid.UUID) -> None:
    clip_id = await db.scalar(select(Frame.clip_id).where(Frame.id == frame_id))
    if clip_id is not None:
        await publish("frame.updated", clip_id=str(clip_id), frame_id=str(frame_id))


@router.post("", response_model=DetectionRead, status_code=201)
async def create_detection(
    payload: DetectionCreate,
    db: AsyncSession = Depends(get_db),
) -> DetectionModel:
    frame = await db.get(Frame, payload.frame_id)
    if frame is None:
        raise HTTPException(status_code=404, detail="Frame not found")

    detection = DetectionModel(
        frame_id=payload.frame_id,
        class_id=payload.class_id,
        subclass_id=payload.subclass_id,
        bbox=payload.bbox.model_dump(),
        source="user",
        reviewed=True,  # a deliberately drawn box is ground truth
        reviewed_at=datetime.now(UTC),
    )
    db.add(detection)
    await db.flush()
    db.add(
        _audit(
            detection,
            reason="user_reassign",
            to_class_id=payload.class_id,
            to_subclass_id=payload.subclass_id,
        )
    )
    await db.commit()
    await db.refresh(detection)
    await _publish_frame_updated(db, detection.frame_id)
    await maybe_trigger_training(db, {detection.class_id})
    return detection


@router.patch("/{detection_id}", response_model=DetectionRead)
async def update_detection(
    detection_id: uuid.UUID,
    payload: DetectionUpdate,
    db: AsyncSession = Depends(get_db),
) -> DetectionModel:
    detection = await db.get(DetectionModel, detection_id)
    if detection is None or detection.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Detection not found")

    data = payload.model_dump(exclude_unset=True)

    class_changed = "class_id" in data and data["class_id"] != detection.class_id
    subclass_changed = (
        "subclass_id" in data and data["subclass_id"] != detection.subclass_id
    )
    if class_changed or subclass_changed:
        db.add(
            _audit(
                detection,
                reason="user_reassign",
                from_class_id=detection.class_id,
                to_class_id=data["class_id"] if class_changed else detection.class_id,
                from_subclass_id=detection.subclass_id,
                to_subclass_id=data["subclass_id"]
                if subclass_changed
                else detection.subclass_id,
            )
        )
        if class_changed:
            detection.class_id = data["class_id"]
        if subclass_changed:
            detection.subclass_id = data["subclass_id"]

    if data.get("bbox") is not None:
        detection.bbox = data["bbox"]

    if "reviewed" in data:
        if data["reviewed"] and not detection.reviewed:
            detection.reviewed = True
            detection.reviewed_at = datetime.now(UTC)
            db.add(_audit(detection, reason="user_review", to_class_id=detection.class_id))
        elif data["reviewed"] is False:
            detection.reviewed = False
            detection.reviewed_at = None

    await db.commit()
    await db.refresh(detection)
    await _publish_frame_updated(db, detection.frame_id)
    if class_changed or subclass_changed or "reviewed" in data:
        await maybe_trigger_training(db, {detection.class_id})
    return detection


@router.delete("/{detection_id}", status_code=204)
async def delete_detection(
    detection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    detection = await db.get(DetectionModel, detection_id)
    if detection is None or detection.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Detection not found")

    detection.deleted_at = datetime.now(UTC)
    db.add(_audit(detection, reason="user_delete", from_class_id=detection.class_id))
    await db.commit()
    await _publish_frame_updated(db, detection.frame_id)


@router.post("/{detection_id}/restore", response_model=DetectionRead)
async def restore_detection(
    detection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> DetectionModel:
    detection = await db.get(DetectionModel, detection_id)
    if detection is None:
        raise HTTPException(status_code=404, detail="Detection not found")

    detection.deleted_at = None
    await db.commit()
    await db.refresh(detection)
    await _publish_frame_updated(db, detection.frame_id)
    return detection


@router.post("/{detection_id}/predict", status_code=202)
async def predict_detection(
    detection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Kick off a YOLO prediction for a user-drawn box.

    The actual work runs on the gpu worker (`vd.predict_user_detection`),
    which writes back `predicted_class_id` — and `class_id` if the user
    didn't pre-select one — and publishes `frame.updated` over SSE. The
    frontend debounces this call ~1 s after the last draw/resize.
    """
    detection = await db.get(DetectionModel, detection_id)
    if detection is None or detection.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Detection not found")
    enqueue("vd.predict_user_detection", str(detection_id), queue="gpu")
    return Response(status_code=202)


@router.get("/{detection_id}/crop")
async def detection_crop(
    detection_id: uuid.UUID,
    size: int = Query(default=192, ge=32, le=512),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Return a cached JPEG of the detection's bbox, generating it on first hit.

    Lets the class gallery render hundreds of tiles without the browser
    downloading the full frame JPEG behind each one.
    """
    row = (
        await db.execute(
            select(DetectionModel.bbox, Frame.path)
            .join(Frame, Frame.id == DetectionModel.frame_id)
            .where(DetectionModel.id == detection_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Detection not found")
    bbox, frame_path = row
    if frame_path is None:
        raise HTTPException(status_code=410, detail="Frame image purged")

    path = ensure_crop(str(detection_id), frame_path, bbox, size)
    if path is None:
        raise HTTPException(status_code=404, detail="Frame image unavailable")
    return FileResponse(
        path,
        media_type="image/jpeg",
        # Filename includes a bbox hash, so the bytes are immutable per URL.
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.post("/{detection_id}/promote-example", response_model=DetectionRead)
async def promote_example(
    detection_id: uuid.UUID,
    payload: PromoteExample,
    db: AsyncSession = Depends(get_db),
) -> DetectionModel:
    """Curate this detection into the sub-class's kNN reference set.

    Assigns the sub-class if it differs, inserts the `subclass_examples` row,
    and — if the crop has no embedding yet — schedules one so the example is
    usable as a kNN reference.
    """
    detection = await db.get(DetectionModel, detection_id)
    if detection is None or detection.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Detection not found")
    subclass = await db.get(Subclass, payload.subclass_id)
    if subclass is None:
        raise HTTPException(status_code=404, detail="Sub-class not found")
    if subclass.class_id != detection.class_id:
        raise HTTPException(
            status_code=409, detail="Sub-class belongs to a different class"
        )

    if detection.subclass_id != payload.subclass_id:
        db.add(
            _audit(
                detection,
                reason="user_reassign",
                from_class_id=detection.class_id,
                to_class_id=detection.class_id,
                from_subclass_id=detection.subclass_id,
                to_subclass_id=payload.subclass_id,
            )
        )
        detection.subclass_id = payload.subclass_id

    if not await db.scalar(
        select(SubclassExample).where(
            SubclassExample.subclass_id == payload.subclass_id,
            SubclassExample.detection_id == detection_id,
        )
    ):
        db.add(
            SubclassExample(subclass_id=payload.subclass_id, detection_id=detection_id)
        )
    await db.commit()
    await db.refresh(detection)

    cls = await db.get(Class, detection.class_id) if detection.class_id else None
    if cls is not None:
        if cls.name == "person" and detection.face_embedding is None:
            enqueue("vd.recognize_face", str(detection_id), queue="gpu")
        elif cls.name != "person" and detection.object_embedding is None:
            enqueue("vd.embed_object", str(detection_id), queue="gpu")

    await _publish_frame_updated(db, detection.frame_id)
    await maybe_trigger_training(db, {detection.class_id})
    return detection

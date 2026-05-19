"""Build the external-job result payload (spec 04 §Jobs).

Shared by the API (`GET /api/jobs/{id}`) and the worker (`vd.deliver_callback`)
so both emit an identical body. Computed on the fly from current detection
state — there is no stored job-result table, so a clip re-reviewed by a human
later changes a subsequent `GET /api/jobs/{id}`; the webhook body is the
snapshot frozen at `clip.done`.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Class, Clip, DetectionModel, Frame, Subclass

_TERMINAL = ("done", "failed")


async def build_job_result(session: AsyncSession, clip: Clip) -> dict[str, Any]:
    """Render `clip` as a job result. `clip` is the submitted clip; if its
    bytes deduped onto an earlier one, detections are read from that canonical
    clip while the correlation fields stay those of the submitted job."""
    result_clip = clip
    if clip.canonical_clip_id is not None:
        canon = await session.get(Clip, clip.canonical_clip_id)
        if canon is not None:
            result_clip = canon

    payload: dict[str, Any] = {
        "job_id": str(clip.id),
        "clip_id": str(result_clip.id),
        "source": clip.source,
        "external_id": clip.external_id,
        "status": result_clip.status,
    }
    if result_clip.status not in _TERMINAL:
        return payload  # still in flight — status only
    if result_clip.status == "failed":
        payload["error"] = result_clip.error
        return payload

    payload["clip"] = {
        "duration_sec": (
            float(result_clip.duration_sec)
            if result_clip.duration_sec is not None
            else None
        ),
        "width": result_clip.width,
        "height": result_clip.height,
    }

    rows = list(
        await session.execute(
            select(
                DetectionModel.confidence_class,
                DetectionModel.confidence_subclass,
                DetectionModel.bbox,
                Frame.frame_index,
                Frame.timestamp_sec,
                Class.name,
                Subclass.name,
            )
            .join(Frame, Frame.id == DetectionModel.frame_id)
            .join(Class, Class.id == DetectionModel.class_id, isouter=True)
            .join(Subclass, Subclass.id == DetectionModel.subclass_id, isouter=True)
            .where(
                Frame.clip_id == result_clip.id,
                Frame.kept.is_(True),
                DetectionModel.deleted_at.is_(None),
            )
            .order_by(Frame.frame_index)
        )
    )

    detections: list[dict[str, Any]] = []
    class_frames: dict[str, set[int]] = {}
    subclass_frames: dict[tuple[str, str], set[int]] = {}
    subclass_best: dict[tuple[str, str], float] = {}
    for conf_c, conf_s, bbox, frame_index, ts, class_name, subclass_name in rows:
        detections.append(
            {
                "class": class_name,
                "subclass": subclass_name,
                "confidence_class": conf_c,
                "confidence_subclass": conf_s,
                "frame_index": frame_index,
                "timestamp_sec": float(ts),
                "bbox": bbox,
            }
        )
        if class_name is not None:
            class_frames.setdefault(class_name, set()).add(frame_index)
            if subclass_name is not None:
                key = (class_name, subclass_name)
                subclass_frames.setdefault(key, set()).add(frame_index)
                if conf_s is not None:
                    subclass_best[key] = max(subclass_best.get(key, 0.0), conf_s)

    payload["detections"] = detections
    payload["summary"] = {
        "classes": [
            {"class": name, "frames": len(frames)}
            for name, frames in sorted(class_frames.items())
        ],
        "subclasses": [
            {
                "class": cls,
                "subclass": sub,
                "frames": len(subclass_frames[(cls, sub)]),
                "best_confidence": subclass_best.get((cls, sub)),
            }
            for (cls, sub) in sorted(subclass_frames)
        ],
    }
    return payload

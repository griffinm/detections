"""Model-version activation — the single transaction that flips `is_active`.

Used by both the API (`POST /models/{id}/activate`) and the worker (a training
task auto-activating its result), so the "exactly one active per
(kind, target_class_id)" invariant and the YOLO class-index sync live once.
"""

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Class, ModelVersion


async def activate_model_version(session: AsyncSession, version: ModelVersion) -> None:
    """Make `version` the active model for its (kind, target_class_id).

    Deactivates every sibling of the same kind/target, activates `version`, and
    — for YOLO versions — rewrites `classes.yolo_class_index` from the version's
    recorded class-name list so `detect_frame_batch` maps indices correctly.
    Rolling back to the COCO base restores COCO indices the same way.

    The caller commits the session and publishes any `model.active_changed`
    event.
    """
    await session.execute(
        update(ModelVersion)
        .where(
            ModelVersion.kind == version.kind,
            ModelVersion.target_class_id.is_not_distinct_from(version.target_class_id),
            ModelVersion.id != version.id,
            ModelVersion.is_active.is_(True),
        )
        .values(is_active=False)
    )
    version.is_active = True

    if version.kind == "yolo":
        await _sync_yolo_class_index(session, version)


async def _sync_yolo_class_index(session: AsyncSession, version: ModelVersion) -> None:
    """Point each `Class.yolo_class_index` at this YOLO model's index for it.

    `version.metrics["class_names"]` is `{index_str: class_name}`. Classes the
    model does not know about are cleared to NULL — `detect_frame_batch` drops
    detections of any class whose `yolo_class_index` is NULL.
    """
    class_names: dict[str, str] = (version.metrics or {}).get("class_names", {})
    index_by_name = {name: int(idx) for idx, name in class_names.items()}

    await session.execute(update(Class).values(yolo_class_index=None))
    for name, idx in index_by_name.items():
        await session.execute(
            update(Class).where(Class.name == name).values(yolo_class_index=idx)
        )

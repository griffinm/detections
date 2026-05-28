"""Resolve the active model versions the worker runs inference with."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vd_db import to_stored_path
from vd_db.models import ModelVersion
from vd_ml import ensure_base_weights, load_yolo
from vd_settings import Settings


async def get_or_register_yolo(session: AsyncSession, settings: Settings) -> ModelVersion:
    """Return the active YOLO `model_versions` row.

    On first run there is no active version, so the COCO-pretrained base is
    downloaded and registered. Its class-name list is stored in `metrics` so
    detections can be traced back to the exact label set the model emitted.
    """
    active = await session.scalar(
        select(ModelVersion).where(
            ModelVersion.kind == "yolo", ModelVersion.is_active.is_(True)
        )
    )
    if active is not None:
        return active

    weights = ensure_base_weights(settings.models_dir, settings.yolo_base_model)
    model = load_yolo(str(weights))
    class_names = {str(idx): name for idx, name in model.names.items()}

    version = ModelVersion(
        kind="yolo",
        name="yolo11l-coco-base",
        weights_path=to_stored_path(settings.models_dir, weights),
        metrics={"class_names": class_names, "source": "coco-pretrained"},
        is_active=True,
    )
    session.add(version)
    await session.commit()
    return version

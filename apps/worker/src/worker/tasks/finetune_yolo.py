"""`vd.finetune_yolo` — fine-tune the YOLO detector on reviewed labels.

Builds a dataset from every ground-truth detection (across all classes — so the
model does not forget COCO classes), trains from the current active checkpoint,
and activates the result only if it clears the mAP regression guard.

Training failures (OOM, bad data) are terminal: the run is marked `failed` and
the task returns normally — no Celery retry, unlike the lightweight tasks.
"""

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

from vd_db import activate_model_version, load_effective_settings
from vd_db.models import ModelVersion, TrainingRun
from vd_tasks.app import celery_app

from worker.dataset import build_yolo_dataset
from worker.db import db_session
from worker.events import publish
from worker.models import get_or_register_yolo


async def _finetune_yolo_async(training_run_id: str) -> str:
    # Imported here, not at module scope: the cpu worker lacks the gpu deps.
    from vd_ml import train_yolo, unload_inference_models

    run_id = uuid.UUID(training_run_id)

    async with db_session() as session:
        settings = await load_effective_settings(session)
        run = await session.get(TrainingRun, run_id)
        if run is None:
            return "missing"
        if run.status in ("succeeded", "cancelled"):
            return run.status
        run.status = "running"
        run.started_at = datetime.now(UTC)
        await session.commit()

        version = await get_or_register_yolo(session, settings)
        base_weights = version.weights_path
        prev_map = (version.metrics or {}).get("val_map50_95")

        manifest = await build_yolo_dataset(session, settings, run_id)
        if manifest.counts["train"] == 0:
            run.status = "failed"
            run.error = "no reviewed or user-drawn detections available to train on"
            run.finished_at = datetime.now(UTC)
            await session.commit()
            await publish(
                "training_run.update", training_run_id=training_run_id, status="failed"
            )
            return "failed"

    await publish("training_run.update", training_run_id=training_run_id, status="running")

    # The detector, face, and DINOv2 models are normally kept resident across
    # tasks so detection stays warm. They'd leave no headroom for fine-tuning
    # at imgsz=960 batch=16 on a 16 GB GPU — the resulting OOM auto-recovery
    # corrupts cuDNN state and the run dies with
    # CUDNN_STATUS_EXECUTION_FAILED_CUDART. Wipe them; the next inference
    # task transparently re-loads them via the `lru_cache` loaders.
    unload_inference_models()

    # Train in a worker thread; bridge per-epoch progress back onto the loop.
    loop = asyncio.get_running_loop()
    progress: asyncio.Queue[tuple[int, int]] = asyncio.Queue()

    def on_epoch_end(epoch: int, total: int, metrics: dict[str, float]) -> None:
        loop.call_soon_threadsafe(progress.put_nowait, (epoch, total))

    train_task = asyncio.create_task(
        asyncio.to_thread(
            train_yolo,
            base_weights,
            str(manifest.data_yaml),
            f"run_{run_id}",
            str(settings.models_dir / "yolo" / "runs"),
            settings.yolo_finetune_epochs,
            settings.yolo_finetune_imgsz,
            0,
            on_epoch_end,
        )
    )
    while not train_task.done():
        try:
            epoch, total = await asyncio.wait_for(progress.get(), timeout=2.0)
        except TimeoutError:
            continue
        await publish(
            "training_run.update",
            training_run_id=training_run_id,
            status="running",
            epoch=epoch,
            total_epochs=total,
        )

    try:
        result = await train_task
    except Exception as exc:  # OOM / bad data — terminal, no retry
        async with db_session() as session:
            run = await session.get(TrainingRun, run_id)
            if run is not None:
                run.status = "failed"
                run.error = str(exc)[:2000]
                run.finished_at = datetime.now(UTC)
                await session.commit()
        await publish(
            "training_run.update", training_run_id=training_run_id, status="failed"
        )
        return "failed"

    async with db_session() as session:
        new_version = ModelVersion(
            kind="yolo",
            name=f"yolo11l-ft-{run_id.hex[:8]}",
            weights_path=result.best_weights,
            trained_on=manifest.counts["detections"],
            metrics={
                "class_names": {str(i): n for i, n in enumerate(manifest.class_names)},
                "source": "finetune",
                "training_run_id": training_run_id,
                "val_map50_95": result.map50_95,
                "val_map50": result.map50,
                "precision": result.precision,
                "recall": result.recall,
            },
            is_active=False,
        )
        session.add(new_version)
        await session.flush()

        # Regression guard: a worse model is registered but not activated.
        activate = prev_map is None or result.map50_95 >= prev_map - 0.01
        if activate:
            await activate_model_version(session, new_version)

        run = await session.get(TrainingRun, run_id)
        assert run is not None
        run.status = "succeeded"
        run.finished_at = datetime.now(UTC)
        run.log_path = str(Path(result.best_weights).parent.parent / "results.csv")
        run.metrics = {
            "val_map50_95": result.map50_95,
            "val_map50": result.map50,
            "precision": result.precision,
            "recall": result.recall,
            "activated": activate,
            "prev_map50_95": prev_map,
            "dataset": manifest.counts,
            "model_version_id": str(new_version.id),
        }
        await session.commit()
        new_version_id = str(new_version.id)

    await publish("training_run.update", training_run_id=training_run_id, status="succeeded")
    if activate:
        await publish("model.active_changed", kind="yolo", model_version_id=new_version_id)
    return new_version_id


@celery_app.task(name="vd.finetune_yolo", bind=True, max_retries=3)
def finetune_yolo(self, training_run_id: str) -> str:  # type: ignore[misc]
    try:
        return asyncio.run(_finetune_yolo_async(training_run_id))
    except Exception as exc:
        # Only infrastructure errors reach here — training failures are caught
        # inside the async core and recorded on the run.
        raise self.retry(exc=exc, countdown=30) from exc

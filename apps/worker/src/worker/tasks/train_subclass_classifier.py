"""`vd.train_subclass_classifier` — fit a per-class sub-class classifier.

Trains a logistic regression over the class's crop embeddings and activates it.
Once active, `vd.assign_subclass` uses it (Regime B) in preference to the kNN
bootstrap. Like `finetune_yolo`, training failures are terminal (no retry).
"""

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vd_db import activate_model_version, to_stored_path
from vd_db.models import (
    Class,
    DetectionModel,
    ModelVersion,
    Subclass,
    SubclassExample,
    TrainingRun,
)
from vd_settings import Settings
from vd_tasks.app import celery_app

from worker.db import db_session
from worker.events import publish


async def _collect_examples(
    session: AsyncSession, class_id: uuid.UUID
) -> tuple[list[list[float]], list[str]]:
    """Embeddings + sub-class labels for a class's reviewed detections + examples.

    Person sub-classes use the face embedding, everything else the object
    embedding. A detection that is both reviewed and a curated example is
    counted once, with the example's sub-class taking precedence.
    """
    cls = await session.get(Class, class_id)
    use_face = cls is not None and cls.name == "person"
    emb = DetectionModel.face_embedding if use_face else DetectionModel.object_embedding

    reviewed = await session.execute(
        select(DetectionModel.id, DetectionModel.subclass_id, emb).where(
            DetectionModel.class_id == class_id,
            DetectionModel.deleted_at.is_(None),
            DetectionModel.subclass_id.is_not(None),
            DetectionModel.reviewed.is_(True),
            emb.is_not(None),
        )
    )
    examples = await session.execute(
        select(DetectionModel.id, SubclassExample.subclass_id, emb)
        .join(SubclassExample, SubclassExample.detection_id == DetectionModel.id)
        .join(Subclass, Subclass.id == SubclassExample.subclass_id)
        .where(
            Subclass.class_id == class_id,
            Subclass.is_active.is_(True),
            DetectionModel.deleted_at.is_(None),
            emb.is_not(None),
        )
    )

    by_detection: dict[uuid.UUID, tuple[list[float], str]] = {}
    for det_id, subclass_id, embedding in [*reviewed, *examples]:
        by_detection[det_id] = ([float(v) for v in embedding], str(subclass_id))
    embeddings = [emb for emb, _ in by_detection.values()]
    labels = [label for _, label in by_detection.values()]
    return embeddings, labels


async def _fail_run(run_id: uuid.UUID, training_run_id: str, message: str) -> str:
    async with db_session() as session:
        run = await session.get(TrainingRun, run_id)
        if run is not None:
            run.status = "failed"
            run.error = message
            run.finished_at = datetime.now(UTC)
            await session.commit()
    await publish("training_run.update", training_run_id=training_run_id, status="failed")
    return "failed"


async def _train_subclass_classifier_async(training_run_id: str) -> str:
    from vd_ml import train_subclass_classifier

    settings = Settings()
    run_id = uuid.UUID(training_run_id)

    async with db_session() as session:
        run = await session.get(TrainingRun, run_id)
        if run is None:
            return "missing"
        if run.status in ("succeeded", "cancelled"):
            return run.status
        if run.target_class_id is None:
            return await _fail_run(run_id, training_run_id, "run has no target_class_id")
        class_id = run.target_class_id
        run.status = "running"
        run.started_at = datetime.now(UTC)
        await session.commit()

        embeddings, labels = await _collect_examples(session, class_id)

    if not embeddings:
        return await _fail_run(
            run_id, training_run_id, "no labeled detections with embeddings for this class"
        )
    if len(set(labels)) < 2:
        return await _fail_run(
            run_id,
            training_run_id,
            f"need at least 2 labeled sub-classes; found {len(set(labels))}",
        )

    await publish("training_run.update", training_run_id=training_run_id, status="running")

    out_path = settings.models_dir / "classifiers" / str(class_id) / f"{run_id}.joblib"
    try:
        result = await asyncio.to_thread(
            train_subclass_classifier, embeddings, labels, str(out_path)
        )
    except Exception as exc:
        return await _fail_run(run_id, training_run_id, str(exc)[:2000])

    async with db_session() as session:
        new_version = ModelVersion(
            kind="classifier",
            name=f"subclass-clf-{class_id.hex[:8]}-{run_id.hex[:8]}",
            weights_path=to_stored_path(settings.models_dir, out_path),
            target_class_id=class_id,
            trained_on=result.n_train + result.n_val,
            metrics={
                "val_accuracy": result.val_accuracy,
                "subclass_ids": result.subclass_ids,
                "n_train": result.n_train,
                "n_val": result.n_val,
                "training_run_id": training_run_id,
            },
            is_active=False,
        )
        session.add(new_version)
        await session.flush()
        await activate_model_version(session, new_version)

        run = await session.get(TrainingRun, run_id)
        assert run is not None
        run.status = "succeeded"
        run.finished_at = datetime.now(UTC)
        run.metrics = {
            "val_accuracy": result.val_accuracy,
            "n_train": result.n_train,
            "n_val": result.n_val,
            "model_version_id": str(new_version.id),
        }
        await session.commit()
        new_version_id = str(new_version.id)

    await publish("training_run.update", training_run_id=training_run_id, status="succeeded")
    await publish(
        "model.active_changed",
        kind="classifier",
        target_class_id=str(class_id),
        model_version_id=new_version_id,
    )
    return new_version_id


@celery_app.task(name="vd.train_subclass_classifier", bind=True, max_retries=3)
def train_subclass_classifier(self, training_run_id: str) -> str:  # type: ignore[misc]
    try:
        return asyncio.run(_train_subclass_classifier_async(training_run_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=30) from exc

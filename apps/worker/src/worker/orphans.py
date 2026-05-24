"""Recovery pass for training runs orphaned by a worker restart.

A `TrainingRun` flips to `status='running'` when the task picks it up and
only flips again on success or caught failure. If the worker process is
killed mid-run (OOM, container restart, deploy) the row stays `running`
forever and the UI shows phantom in-progress training. This module flips
those rows to `failed` at worker boot — single-host single-worker means
nothing can outlive the restart, so any `running` row is by definition stale.
"""

import asyncio
import logging
from datetime import UTC, datetime

from celery.signals import worker_ready
from sqlalchemy import select, update

from vd_db.models import TrainingRun

from worker.db import db_session
from worker.events import publish

logger = logging.getLogger(__name__)

_ORPHAN_ERROR = "worker restarted before completion"


async def _sweep_orphan_training_runs() -> list[str]:
    async with db_session() as session:
        ids = list(
            await session.scalars(
                select(TrainingRun.id).where(TrainingRun.status == "running")
            )
        )
        if not ids:
            return []
        await session.execute(
            update(TrainingRun)
            .where(TrainingRun.id.in_(ids))
            .values(
                status="failed",
                error=_ORPHAN_ERROR,
                finished_at=datetime.now(UTC),
            )
        )
        await session.commit()

    str_ids = [str(i) for i in ids]
    for run_id in str_ids:
        await publish("training_run.update", training_run_id=run_id, status="failed")
    return str_ids


@worker_ready.connect
def _on_worker_ready(sender=None, **_: object) -> None:  # type: ignore[no-untyped-def]
    # Only the worker that owns the `train` queue knows the real liveness of
    # training runs. The cpu worker shares this codebase but consumes other
    # queues — it must not touch training_runs at boot.
    try:
        consumed = {q.name for q in sender.consumer.task_consumer.queues}
    except AttributeError:
        return
    if "train" not in consumed:
        return
    try:
        swept = asyncio.run(_sweep_orphan_training_runs())
    except Exception:
        logger.exception("orphan training-run sweep failed")
        return
    if swept:
        logger.warning("marked %d orphan training run(s) as failed: %s", len(swept), swept)

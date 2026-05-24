from vd_tasks.app import celery_app

celery_app.autodiscover_tasks(["worker.tasks"])

# Side-effect import: registers the `worker_ready` handler that fails orphan
# training runs left `running` by a previous worker crash.
from worker import orphans  # noqa: E402, F401

__all__ = ["celery_app"]

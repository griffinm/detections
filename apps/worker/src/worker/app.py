from vd_tasks.app import celery_app

celery_app.autodiscover_tasks(["worker.tasks"])

__all__ = ["celery_app"]

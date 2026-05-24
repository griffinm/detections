from celery import Celery
from vd_settings import Settings

_settings = Settings()

celery_app = Celery(
    "vd",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    task_routes={
        "vd.ingest_video": {"queue": "cpu"},
        "vd.extract_frames": {"queue": "cpu"},
        "vd.prune_frame": {"queue": "cpu"},
        "vd.purge_frames": {"queue": "cpu"},
        "vd.delete_clip": {"queue": "cpu"},
        "vd.deliver_callback": {"queue": "cpu"},
        "vd.compress_video": {"queue": "gpu"},
        "vd.detect_frame_batch": {"queue": "gpu"},
        "vd.recognize_face": {"queue": "gpu"},
        "vd.embed_object": {"queue": "gpu"},
        "vd.assign_subclass": {"queue": "gpu"},
        "vd.backfill_embeddings": {"queue": "gpu"},
        "vd.finetune_yolo": {"queue": "train"},
        "vd.train_subclass_classifier": {"queue": "train"},
        "vd.backfill_detections": {"queue": "gpu"},
    },
)

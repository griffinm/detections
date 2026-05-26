from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Walk up from this file to find the repo root .env (works regardless of CWD).
_here = Path(__file__).resolve()
_repo_root = next(
    (p for p in _here.parents if (p / ".env").exists()),
    _here.parents[4],
)
_ENV_FILE = _repo_root / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_prefix="VD_",
        extra="ignore",
    )

    # storage
    inbox_dir: Path = Path("/data/videos/inbox")
    intake_dir: Path = Path("/data/videos/intake")
    processed_dir: Path = Path("/data/videos/processed")
    failed_dir: Path = Path("/data/videos/failed")
    frames_dir: Path = Path("/data/frames")
    models_dir: Path = Path("/data/models")

    # database
    database_url: str = "postgresql+asyncpg://vd:vd@localhost:5432/video_detection"

    # queue
    redis_url: str = "redis://localhost:6379/0"

    # processing
    frame_fps: float = 1.0
    detection_min_confidence: float = 0.25
    subclass_min_confidence: float = 0.55
    frame_jpeg_quality: int = 90
    detect_batch_size: int = 16

    # training
    subclass_retrain_threshold: int = 25
    yolo_base_model: str = "yolo11l.pt"
    yolo_finetune_epochs: int = 50
    yolo_finetune_imgsz: int = 960
    # Activation guard: a new fine-tune activates only if its aggregate val
    # mAP50-95 is within `yolo_regression_tolerance` of the previous active's,
    # AND every class with ≥ `yolo_per_class_min_val_samples` val labels in
    # both models stays within `yolo_per_class_regression_tolerance`. The
    # per-class tolerance is looser because per-class AP is noisier on small
    # val splits.
    yolo_regression_tolerance: float = 0.01
    yolo_per_class_regression_tolerance: float = 0.05
    yolo_per_class_min_val_samples: int = 10
    insightface_pack: str = "buffalo_l"

    # retention
    delete_processed_videos: bool = False
    # post-extract compression (hevc_nvenc, runs on the gpu worker)
    compress_processed_videos: bool = True
    compress_crf: int = 22

    # near-duplicate frame pruning
    prune_similar_frames: bool = True
    frame_similarity_threshold: int = 6

    # external job submission (POST /api/jobs callbacks)
    webhook_timeout_sec: float = 10.0
    webhook_max_attempts: int = 5


# Settings the owner may retune at runtime via the settings_kv table (the
# /settings page); paths, URLs, and model identity stay env-only.
OVERRIDABLE_KEYS: tuple[str, ...] = (
    "frame_fps",
    "detection_min_confidence",
    "subclass_min_confidence",
    "frame_jpeg_quality",
    "detect_batch_size",
    "subclass_retrain_threshold",
    "yolo_finetune_epochs",
    "yolo_finetune_imgsz",
    "yolo_regression_tolerance",
    "yolo_per_class_regression_tolerance",
    "yolo_per_class_min_val_samples",
    "delete_processed_videos",
    "compress_processed_videos",
    "compress_crf",
    "prune_similar_frames",
    "frame_similarity_threshold",
)

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
    custom_class_finetune_threshold: int = 100
    subclass_retrain_threshold: int = 25
    yolo_base_model: str = "yolo11l.pt"
    yolo_finetune_epochs: int = 50
    yolo_finetune_imgsz: int = 960
    insightface_pack: str = "buffalo_l"

    # retention
    delete_processed_videos: bool = False
    delete_frames_without_objects: bool = True


# Settings the owner may retune at runtime via the settings_kv table (the
# /settings page); paths, URLs, and model identity stay env-only.
OVERRIDABLE_KEYS: tuple[str, ...] = (
    "frame_fps",
    "detection_min_confidence",
    "subclass_min_confidence",
    "frame_jpeg_quality",
    "detect_batch_size",
    "custom_class_finetune_threshold",
    "subclass_retrain_threshold",
    "yolo_finetune_epochs",
    "yolo_finetune_imgsz",
    "delete_processed_videos",
    "delete_frames_without_objects",
)

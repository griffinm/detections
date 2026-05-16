import logging
import time
from pathlib import Path

from watchdog.events import FileClosedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from vd_settings import Settings
from vd_tasks.app import celery_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm"}


def _dispatch(path: Path) -> None:
    celery_app.send_task("vd.ingest_video", args=[str(path)], queue="cpu")
    logger.info("Queued %s", path.name)


class VideoHandler(FileSystemEventHandler):
    def on_closed(self, event: FileClosedEvent) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        path = Path(str(event.src_path))
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            return
        _dispatch(path)


def _scan_existing(inbox: Path) -> None:
    for ext in VIDEO_EXTENSIONS:
        for path in inbox.glob(f"*{ext}"):
            logger.info("Found existing file on startup: %s", path.name)
            _dispatch(path)


def main() -> None:
    settings = Settings()
    inbox = settings.inbox_dir
    inbox.mkdir(parents=True, exist_ok=True)

    _scan_existing(inbox)

    logger.info("Watching %s", inbox)
    handler = VideoHandler()
    observer = Observer()
    observer.schedule(handler, str(inbox), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()

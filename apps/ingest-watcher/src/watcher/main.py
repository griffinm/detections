import logging
import time
from pathlib import Path

from watchdog.events import (
    FileClosedEvent,
    FileCreatedEvent,
    FileSystemEventHandler,
    FileSystemMovedEvent,
)
from watchdog.observers.polling import PollingObserver

from vd_settings import Settings
from vd_tasks.app import celery_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm"}


def _dispatch(path: Path) -> None:
    celery_app.send_task("vd.ingest_video", args=[str(path)], queue="cpu")
    logger.info("Queued %s", path.name)


class VideoHandler(FileSystemEventHandler):
    def on_created(self, event: FileCreatedEvent) -> None:  # type: ignore[override]
        # The primary signal under PollingObserver: it never emits `on_closed`
        # (that's an inotify IN_CLOSE_WRITE), and it only emits `on_moved` when
        # the upload's `.part` file happens to be captured in a snapshot before
        # its rename. A fast upload writes the `.part` and renames it to the
        # final video name within a single poll interval, so the poller never
        # sees the `.part` — it just sees the finished video appear, i.e. a
        # create event. Without this handler those uploads are silently dropped.
        # The `.part` file itself is ignored here by its non-video suffix.
        if event.is_directory:
            return
        path = Path(str(event.src_path))
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            return
        _dispatch(path)

    def on_closed(self, event: FileClosedEvent) -> None:  # type: ignore[override]
        # IN_CLOSE_WRITE — a file written and closed in place (e.g. `cp`, or a
        # browser upload streamed straight to its final name). Only fires under
        # the inotify-backed Observer; kept for that fallback. `vd.ingest_video`
        # is idempotent (SHA dedup), so overlap with `on_created` is harmless.
        if event.is_directory:
            return
        path = Path(str(event.src_path))
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            return
        _dispatch(path)

    def on_moved(self, event: FileSystemMovedEvent) -> None:  # type: ignore[override]
        # IN_MOVED_TO — an atomic rename into the inbox. The API's upload
        # endpoint streams to a hidden `.part` file then renames it to the
        # final video name; that rename is a move, not a close, so it would be
        # missed without this handler. The renamed file is already complete.
        if event.is_directory:
            return
        path = Path(str(event.dest_path))
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
    # PollingObserver, not the default inotify-backed Observer: the inbox is
    # bind-mounted from a network share, and inotify does not fire for writes
    # originating on other hosts. Polling stat-walks the directory and
    # synthesizes events, which works on every filesystem.
    observer = PollingObserver()
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

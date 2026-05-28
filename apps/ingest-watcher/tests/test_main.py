"""Watcher dispatch tests — the event→ingest mapping, with Celery faked.

Regression cover for the bug where a fast UI upload was silently dropped:
under `PollingObserver` the renamed video surfaces as a *create* event (the
`.part` file never survives a poll interval), and the handler had no
`on_created`, so nothing was enqueued.
"""

import pytest
from watchdog.events import FileCreatedEvent, FileMovedEvent

from watcher import main as wm

INBOX = "/data/videos/inbox"


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list:
    calls: list = []
    monkeypatch.setattr(
        wm.celery_app, "send_task",
        lambda name, args=None, **kw: calls.append((name, args, kw.get("queue"))),
    )
    return calls


def test_on_created_dispatches_a_finished_video(sent: list) -> None:
    wm.VideoHandler().on_created(FileCreatedEvent(f"{INBOX}/clip.mp4"))
    assert sent == [("vd.ingest_video", [f"{INBOX}/clip.mp4"], "cpu")]


def test_on_created_ignores_the_part_file(sent: list) -> None:
    # The upload's hidden temp file must not trigger ingest of a half-written
    # video; the non-video suffix is what filters it out.
    wm.VideoHandler().on_created(FileCreatedEvent(f"{INBOX}/.upload-abc.mp4.part"))
    assert sent == []


def test_on_created_ignores_directories(sent: list) -> None:
    evt = FileCreatedEvent(f"{INBOX}/subdir")
    evt.is_directory = True
    wm.VideoHandler().on_created(evt)
    assert sent == []


def test_on_moved_dispatches_the_destination_video(sent: list) -> None:
    wm.VideoHandler().on_moved(
        FileMovedEvent(f"{INBOX}/.upload-abc.mp4.part", f"{INBOX}/clip.mp4")
    )
    assert sent == [("vd.ingest_video", [f"{INBOX}/clip.mp4"], "cpu")]

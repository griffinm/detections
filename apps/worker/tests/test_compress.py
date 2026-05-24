"""Integration tests for `vd.compress_video`.

ffmpeg/NVENC is not invoked: `asyncio.create_subprocess_exec` is
monkeypatched to capture argv and synthesize an output file so the
atomic replace runs for real.
"""

import asyncio
import uuid
from pathlib import Path

import pytest

from vd_db.models import Clip
from worker.tasks import compress as compress_mod
from worker.tasks.compress import _compress_video_async


class _FakeProc:
    def __init__(self, returncode: int = 0, stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", self._stderr


def _patch_ffmpeg(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returncode: int = 0,
    output_bytes: bytes = b"hevc-fake",
) -> list[tuple[str, ...]]:
    """Record the argv list each ffmpeg call receives and, on success,
    write `output_bytes` to the output path so `os.replace` finds it."""
    captured: list[tuple[str, ...]] = []

    async def fake_exec(*args: str, **kwargs: object) -> _FakeProc:
        captured.append(args)
        if returncode == 0:
            Path(args[-1]).write_bytes(output_bytes)
        return _FakeProc(returncode=returncode, stderr=b"boom" if returncode else b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return captured


async def _noop(*args: object, **kwargs: object) -> None:
    return None


async def _seed_clip(session, tmp_path, *, codec: str | None = "h264"):  # type: ignore[no-untyped-def]
    video = tmp_path / "v.mp4"
    video.write_bytes(b"original-h264-bytes-pretend")
    clip = Clip(
        filename="v.mp4", original_path="/in/v.mp4", final_path=str(video),
        sha256=uuid.uuid4().hex, size_bytes=video.stat().st_size,
        status="done", codec=codec,
    )
    session.add(clip)
    await session.commit()
    return clip, video


async def test_compress_replaces_video_and_updates_clip(  # type: ignore[no-untyped-def]
    session, tmp_path, monkeypatch,
):
    events: list[tuple[str, dict[str, object]]] = []

    async def fake_publish(event_type: str, **kw: object) -> None:
        events.append((event_type, kw))

    monkeypatch.setattr(compress_mod, "publish", fake_publish)
    captured = _patch_ffmpeg(monkeypatch, output_bytes=b"smaller")

    clip, video = await _seed_clip(session, tmp_path)
    original_size = video.stat().st_size

    assert await _compress_video_async(str(clip.id)) is True

    # The ffmpeg argv carries the NVENC encoder, CQ matches settings.compress_crf
    # default, and the output path is the .compress.tmp sibling.
    assert len(captured) == 1
    argv = captured[0]
    assert "hevc_nvenc" in argv
    assert "-cq" in argv and argv[argv.index("-cq") + 1] == "22"
    assert "-c:a" in argv and argv[argv.index("-c:a") + 1] == "copy"
    assert argv[-1].endswith(".compress.tmp.mp4")
    assert Path(argv[-1]).parent == video.parent

    # The original file was replaced atomically, the tmp file is gone.
    assert video.exists()
    assert video.read_bytes() == b"smaller"
    assert not Path(argv[-1]).exists()

    # Clip metadata reflects the new codec + new size.
    session.expunge_all()
    refreshed = await session.get(Clip, clip.id)
    assert refreshed is not None
    assert refreshed.codec == "hevc"
    assert refreshed.size_bytes == len(b"smaller")
    assert refreshed.size_bytes != original_size

    # The published event carries before/after sizes for downstream consumers.
    assert events == [(
        "clip.compressed",
        {"clip_id": str(clip.id), "size_before": original_size,
         "size_after": len(b"smaller")},
    )]


async def test_compress_skips_when_already_hevc(  # type: ignore[no-untyped-def]
    session, tmp_path, monkeypatch,
):
    monkeypatch.setattr(compress_mod, "publish", _noop)
    captured = _patch_ffmpeg(monkeypatch)

    clip, video = await _seed_clip(session, tmp_path, codec="hevc")
    original = video.read_bytes()

    assert await _compress_video_async(str(clip.id)) is False
    assert captured == []
    assert video.read_bytes() == original  # untouched


async def test_compress_skips_when_file_missing(  # type: ignore[no-untyped-def]
    session, tmp_path, monkeypatch,
):
    monkeypatch.setattr(compress_mod, "publish", _noop)
    captured = _patch_ffmpeg(monkeypatch)

    clip, video = await _seed_clip(session, tmp_path)
    video.unlink()

    assert await _compress_video_async(str(clip.id)) is False
    assert captured == []


async def test_compress_cleans_up_tmp_on_failure(  # type: ignore[no-untyped-def]
    session, tmp_path, monkeypatch,
):
    monkeypatch.setattr(compress_mod, "publish", _noop)
    captured = _patch_ffmpeg(monkeypatch, returncode=1)

    clip, video = await _seed_clip(session, tmp_path)
    original = video.read_bytes()

    with pytest.raises(RuntimeError, match="hevc_nvenc exited 1"):
        await _compress_video_async(str(clip.id))

    # On a failed encode, the original is preserved and the tmp is gone.
    assert video.read_bytes() == original
    assert captured  # ffmpeg was invoked once
    tmp_path_used = Path(captured[0][-1])
    assert not tmp_path_used.exists()

    # Clip codec is still the original h264 — no DB write happened.
    session.expunge_all()
    refreshed = await session.get(Clip, clip.id)
    assert refreshed is not None
    assert refreshed.codec == "h264"


async def test_compress_missing_clip_is_noop(  # type: ignore[no-untyped-def]
    session, tmp_path, monkeypatch,
):
    monkeypatch.setattr(compress_mod, "publish", _noop)
    captured = _patch_ffmpeg(monkeypatch)

    assert await _compress_video_async(str(uuid.uuid4())) is False
    assert captured == []

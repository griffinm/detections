"""Integration tests for `vd.deliver_callback`.

The HTTP POST is stubbed by monkeypatching `_post`; everything else — the
`webhook_deliveries` ledger, the result payload, the retry/give-up logic —
runs for real against the test database.
"""

import json
import uuid

import pytest
from sqlalchemy import select

from vd_db.models import Class, Clip, DetectionModel, Frame, WebhookDelivery
from worker.tasks import deliver_callback as dc
from worker.tasks.deliver_callback import _deliver_callback_async


async def _seed_done_clip(session, callback_url="http://hook.test/cb"):  # type: ignore[no-untyped-def]
    clip = Clip(
        filename="t.mp4", original_path="/in/t.mp4", sha256=uuid.uuid4().hex,
        size_bytes=1, status="done", source="unifi-protect", external_id="e1",
        callback_url=callback_url, duration_sec=4, width=640, height=480,
    )
    session.add(clip)
    await session.flush()
    frame = Frame(
        clip_id=clip.id, frame_index=1, timestamp_sec=1, width=640, height=480,
        kept=True, detect_status="done",
    )
    session.add(frame)
    await session.flush()
    person = await session.scalar(select(Class).where(Class.name == "person"))
    session.add(
        DetectionModel(
            frame_id=frame.id, class_id=person.id,
            bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
            confidence_class=0.8, source="model",
        )
    )
    await session.commit()
    return clip


async def test_delivers_and_records(session, monkeypatch):  # type: ignore[no-untyped-def]
    posted: dict[str, object] = {}

    def fake_post(url, body, timeout):  # type: ignore[no-untyped-def]
        posted["url"] = url
        posted["body"] = body
        return 200

    monkeypatch.setattr(dc, "_post", fake_post)
    clip = await _seed_done_clip(session)

    assert await _deliver_callback_async(str(clip.id), "clip.done") is True
    assert posted["url"] == "http://hook.test/cb"
    payload = json.loads(posted["body"])  # type: ignore[arg-type]
    assert payload["status"] == "done"
    assert payload["detections"][0]["class"] == "person"

    session.expunge_all()
    delivery = await session.scalar(
        select(WebhookDelivery).where(WebhookDelivery.clip_id == clip.id)
    )
    assert delivery is not None
    assert delivery.status == "delivered"
    assert delivery.attempts == 1
    assert delivery.response_status == 200


async def test_no_callback_url_is_noop(session, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(dc, "_post", lambda *a: 200)
    clip = await _seed_done_clip(session, callback_url=None)

    assert await _deliver_callback_async(str(clip.id), "clip.done") is False
    assert await session.scalar(
        select(WebhookDelivery).where(WebhookDelivery.clip_id == clip.id)
    ) is None


async def test_gives_up_after_max_attempts(session, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("VD_WEBHOOK_MAX_ATTEMPTS", "1")
    monkeypatch.setattr(dc, "_post", lambda *a: 500)
    clip = await _seed_done_clip(session)

    assert await _deliver_callback_async(str(clip.id), "clip.done") is False
    session.expunge_all()
    delivery = await session.scalar(
        select(WebhookDelivery).where(WebhookDelivery.clip_id == clip.id)
    )
    assert delivery is not None
    assert delivery.status == "failed"
    assert delivery.attempts == 1
    assert delivery.last_error == "HTTP 500"


async def test_retries_before_giving_up(session, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("VD_WEBHOOK_MAX_ATTEMPTS", "3")
    monkeypatch.setattr(dc, "_post", lambda *a: 500)
    clip = await _seed_done_clip(session)

    # Not yet at the cap → raises so Celery retries against the same row.
    with pytest.raises(RuntimeError):
        await _deliver_callback_async(str(clip.id), "clip.done")
    session.expunge_all()
    delivery = await session.scalar(
        select(WebhookDelivery).where(WebhookDelivery.clip_id == clip.id)
    )
    assert delivery is not None
    assert delivery.status == "pending"
    assert delivery.attempts == 1


async def test_already_delivered_is_idempotent(session, monkeypatch):  # type: ignore[no-untyped-def]
    calls: list[object] = []

    def fake_post(url, body, timeout):  # type: ignore[no-untyped-def]
        calls.append(url)
        return 200

    monkeypatch.setattr(dc, "_post", fake_post)
    clip = await _seed_done_clip(session)

    assert await _deliver_callback_async(str(clip.id), "clip.done") is True
    assert await _deliver_callback_async(str(clip.id), "clip.done") is True
    assert len(calls) == 1  # the second call short-circuits on the delivered row

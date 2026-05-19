"""`vd.deliver_callback` — POST a job result to an external app's webhook.

Scheduled when an externally-submitted clip (one carrying a `callback_url`)
reaches a terminal status. The `webhook_deliveries` row is both the ledger and
the idempotency key: keyed on `(clip_id, event)`, a `delivered` row is never
re-sent, and a Celery retry re-runs against that same row.

The result body is built by `vd_db.build_job_result`, the exact payload the
API serves from `GET /api/jobs/{id}` — submitter sees one shape either way.
"""

import asyncio
import json
import logging
import random
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from vd_db import build_job_result
from vd_db.models import Clip, WebhookDelivery
from vd_settings import Settings
from vd_tasks.app import celery_app

from worker.db import db_session

logger = logging.getLogger(__name__)


def _post(url: str, body: bytes, timeout: float) -> int:
    """POST JSON and return the HTTP status. A non-2xx *response* comes back as
    its code; a transport failure (timeout, refused, DNS) raises."""
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


async def _deliver_callback_async(clip_id: str, event: str) -> bool:
    cid = uuid.UUID(clip_id)
    settings = Settings()

    async with db_session() as session:
        clip = await session.get(Clip, cid)
        if clip is None or not clip.callback_url:
            return False  # not an external job, or nothing to deliver to

        payload = await build_job_result(session, clip)
        body = json.dumps(payload).encode()

        # The (clip_id, event) row is the idempotency key — upsert it.
        delivery = await session.scalar(
            select(WebhookDelivery).where(
                WebhookDelivery.clip_id == cid, WebhookDelivery.event == event
            )
        )
        if delivery is None:
            delivery = WebhookDelivery(
                clip_id=cid, event=event, url=clip.callback_url, payload=payload,
                status="pending", attempts=0,
            )
            session.add(delivery)
        elif delivery.status == "delivered":
            return True  # already delivered — idempotent no-op
        else:
            delivery.payload = payload

        delivery.attempts += 1
        delivery.last_attempt_at = datetime.now(UTC)

        try:
            status = await asyncio.to_thread(
                _post, clip.callback_url, body, settings.webhook_timeout_sec
            )
        except Exception as exc:  # transport failure
            delivery.response_status = None
            delivery.last_error = f"{type(exc).__name__}: {exc}"
            ok = False
        else:
            delivery.response_status = status
            ok = 200 <= status < 300
            delivery.last_error = None if ok else f"HTTP {status}"

        if ok:
            delivery.status = "delivered"
            await session.commit()
            return True

        if delivery.attempts >= settings.webhook_max_attempts:
            delivery.status = "failed"
            await session.commit()
            logger.error(
                "deliver_callback: %s for clip %s gave up after %d attempts (%s)",
                event, clip_id, delivery.attempts, delivery.last_error,
            )
            return False

        await session.commit()
        # Surface the failure so Celery retries against this same row.
        raise RuntimeError(
            f"callback {event} for clip {clip_id} failed: {delivery.last_error}"
        )


@celery_app.task(name="vd.deliver_callback", bind=True, max_retries=20)
def deliver_callback(self, clip_id: str, event: str) -> bool:  # type: ignore[misc]
    try:
        return asyncio.run(_deliver_callback_async(clip_id, event))
    except Exception as exc:
        # Exponential backoff + jitter. The real attempt cap is enforced inside
        # the async body via webhook_max_attempts; max_retries here is only a
        # backstop against a bug that raises before the cap is reached.
        countdown = min(2 ** self.request.retries, 300) + random.uniform(0, 5)
        raise self.retry(exc=exc, countdown=countdown) from exc

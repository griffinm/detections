import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TrainingRunRead(BaseModel):
    id: uuid.UUID
    kind: str
    target_class_id: uuid.UUID | None
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    metrics: dict[str, Any] | None
    error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TrainingRunDetail(TrainingRunRead):
    """A run plus the tail of its training log, for the run detail panel."""

    log_tail: str | None = None


class TrainingRunCreate(BaseModel):
    kind: str
    target_class_id: uuid.UUID | None = None


class TrainingRunCounts(BaseModel):
    """Faceted counts for the /training stat strip.

    Buckets collapse the underlying `run_status` enum into the four states the
    UI cares about (running / done / failed / queued). Counts always reflect
    the `kind` filter — but never the `status` filter — so the strip shows what
    *each bucket would contain*, independent of which bucket is selected.
    """

    all: int
    running: int
    done: int
    failed: int
    queued: int

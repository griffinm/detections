import uuid
from datetime import datetime

from pydantic import BaseModel


class ClipDetectionGroup(BaseModel):
    """One (class, sub-class) bucket of non-deleted detections on a clip.

    `subclass_id is None` means the bucket is "this class, no sub-class
    assigned" — still meaningful (e.g. "person 12" with no named identity).
    """

    class_id: uuid.UUID | None
    class_name: str | None
    class_color: str | None
    subclass_id: uuid.UUID | None
    subclass_name: str | None
    subclass_color: str | None
    count: int


class ClipRead(BaseModel):
    id: uuid.UUID
    filename: str
    sha256: str
    size_bytes: int
    duration_sec: float | None
    fps: float | None
    width: int | None
    height: int | None
    codec: str | None
    status: str
    error: str | None
    ingested_at: datetime | None
    processed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Representative frame for list views; injected by the router, None until
    # the clip has at least one kept frame.
    thumbnail_url: str | None = None
    # De-duped per-(class, sub-class) counts; injected by the list router.
    detection_summary: list[ClipDetectionGroup] = []

    model_config = {"from_attributes": True}


class ClipDetail(ClipRead):
    frame_count: int


class ClipClassSummary(BaseModel):
    """How many detections of each class live on a clip — populates the
    bulk-label page's class filter."""

    class_id: uuid.UUID | None
    class_name: str | None
    count: int

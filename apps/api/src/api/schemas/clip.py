import uuid
from datetime import datetime

from pydantic import BaseModel


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

    model_config = {"from_attributes": True}


class ClipDetail(ClipRead):
    frame_count: int

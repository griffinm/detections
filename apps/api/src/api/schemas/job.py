import uuid
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class JobCreate(BaseModel):
    """Body of `POST /api/jobs` — an upstream app submitting a video.

    The video must already be written under `VD_INTAKE_DIR`; only its path is
    passed (the apps share the host filesystem — no bytes over HTTP).
    """

    source: str = Field(min_length=1, max_length=64)
    video_path: str = Field(min_length=1)
    external_id: str | None = Field(default=None, max_length=255)
    callback_url: HttpUrl | None = None
    metadata: dict[str, Any] | None = None


class JobAccepted(BaseModel):
    job_id: uuid.UUID
    status: str

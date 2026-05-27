from pydantic import BaseModel, Field


class DirUsage(BaseModel):
    """Disk footprint of one managed data directory."""

    name: str
    path: str
    bytes: int
    file_count: int


class DiskUsageResponse(BaseModel):
    dirs: list[DirUsage]
    total_bytes: int
    free_bytes: int


class PurgeRequest(BaseModel):
    older_than_days: int = Field(ge=1)


class PurgeResponse(BaseModel):
    enqueued: bool
    older_than_days: int


class TracksBackfillStatus(BaseModel):
    """How many clips still need a Phase-9 backfill run."""

    eligible_clips: int


class TracksBackfillRequest(BaseModel):
    """Sweep-mode backfill request. Targeted backfill of a single clip goes
    via `POST /api/clips/{clip_id}/backfill-tracks` in the clips router."""

    limit: int = Field(default=50, ge=1, le=500)


class TracksBackfillResponse(BaseModel):
    enqueued: bool
    limit: int

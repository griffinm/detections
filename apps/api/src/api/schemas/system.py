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

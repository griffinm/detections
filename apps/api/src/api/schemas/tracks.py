"""Pydantic schemas for the `/api/tracks/*` router."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from .detection import Bbox


class TrackMember(BaseModel):
    """One detection inside a track — shape used by the track-detail view."""

    id: uuid.UUID
    frame_id: uuid.UUID
    frame_index: int
    bbox: Bbox
    class_id: uuid.UUID | None
    subclass_id: uuid.UUID | None
    confidence_class: float | None
    confidence_subclass: float | None
    source: str
    reviewed: bool


class TrackRead(BaseModel):
    """Track summary — list views and the detail header both consume this."""

    id: uuid.UUID
    clip_id: uuid.UUID
    class_id: uuid.UUID | None
    subclass_id: uuid.UUID | None
    predicted_class_id: uuid.UUID | None
    predicted_subclass_id: uuid.UUID | None
    confidence_class: float | None
    confidence_subclass: float | None
    n_detections: int
    first_frame_index: int
    last_frame_index: int
    source: str
    model_version_id: uuid.UUID | None
    reviewed: bool
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TrackDetail(BaseModel):
    """Single-track detail: track header + ordered member detections."""

    track: TrackRead
    members: list[TrackMember]


class TrackUpdate(BaseModel):
    class_id: uuid.UUID | None = None
    subclass_id: uuid.UUID | None = None
    reviewed: bool | None = None


class TrackSplit(BaseModel):
    pivot_frame_index: int = Field(ge=0)


class TrackMerge(BaseModel):
    other_track_id: uuid.UUID


class TrackUpdateResponse(BaseModel):
    track: TrackRead
    updated_detections: int
    audits_written: int
    affected_frame_ids: list[uuid.UUID]

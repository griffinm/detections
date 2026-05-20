import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class Bbox(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


class DetectionRead(BaseModel):
    id: uuid.UUID
    frame_id: uuid.UUID
    class_id: uuid.UUID | None
    subclass_id: uuid.UUID | None
    bbox: Bbox
    confidence_class: float | None
    confidence_subclass: float | None
    source: str
    reviewed: bool
    reviewed_at: datetime | None
    predicted_class_id: uuid.UUID | None
    predicted_subclass_id: uuid.UUID | None
    model_version_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DetectionCreate(BaseModel):
    frame_id: uuid.UUID
    bbox: Bbox
    class_id: uuid.UUID | None = None
    subclass_id: uuid.UUID | None = None


class DetectionUpdate(BaseModel):
    bbox: Bbox | None = None
    class_id: uuid.UUID | None = None
    subclass_id: uuid.UUID | None = None
    reviewed: bool | None = None


class PromoteExample(BaseModel):
    subclass_id: uuid.UUID


class DetectionGalleryItem(BaseModel):
    """A detection tile for the class/sub-class gallery — bbox + frame path.

    Lean shape, distinct from `DetectionRead`: carries only what the gallery
    grid renders (CSS-cropped thumb, reviewed badge, deep-link target).
    """

    id: uuid.UUID
    frame_id: uuid.UUID
    clip_id: uuid.UUID
    class_id: uuid.UUID | None
    subclass_id: uuid.UUID | None
    bbox: Bbox
    image_url: str | None
    source: str
    reviewed: bool
    reviewed_at: datetime | None
    created_at: datetime

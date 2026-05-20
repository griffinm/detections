import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from api.schemas.detection import Bbox


class ClassRead(BaseModel):
    id: uuid.UUID
    name: str
    source: str
    yolo_class_index: int | None
    color_hex: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ClassCreate(BaseModel):
    name: str = Field(min_length=1)
    color_hex: str = "#888888"
    yolo_class_index: int | None = None


class ClassCatalogEntry(BaseModel):
    """A name from the active YOLO model's class list, offered to the picker."""

    name: str
    yolo_class_index: int
    in_use: bool


class ClassUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    color_hex: str | None = None
    is_active: bool | None = None


class SubclassRead(BaseModel):
    id: uuid.UUID
    class_id: uuid.UUID
    name: str
    color_hex: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SubclassCreate(BaseModel):
    name: str = Field(min_length=1)
    color_hex: str = "#888888"


class SubclassUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    color_hex: str | None = None
    is_active: bool | None = None


class SubclassExampleCreate(BaseModel):
    detection_id: uuid.UUID


class SubclassExampleRead(BaseModel):
    """An example crop for the gallery — carries enough to render it client-side."""

    id: uuid.UUID
    subclass_id: uuid.UUID
    detection_id: uuid.UUID
    starred: bool
    created_at: datetime
    bbox: Bbox
    frame_id: uuid.UUID
    image_url: str | None


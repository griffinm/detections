import uuid
from datetime import datetime

from pydantic import BaseModel

from api.schemas.detection import DetectionRead


class FrameRead(BaseModel):
    id: uuid.UUID
    clip_id: uuid.UUID
    frame_index: int
    timestamp_sec: float
    path: str | None
    image_url: str | None = None
    width: int
    height: int
    kept: bool
    detect_status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class FrameDetail(FrameRead):
    detections: list[DetectionRead] = []

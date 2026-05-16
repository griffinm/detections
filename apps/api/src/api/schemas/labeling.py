import uuid

from pydantic import BaseModel


class LabelingQueueItem(BaseModel):
    """One frame in the review queue, with its review backlog summarized."""

    frame_id: uuid.UUID
    clip_id: uuid.UUID
    clip_filename: str
    frame_index: int
    image_url: str | None
    unreviewed_count: int
    min_confidence: float | None

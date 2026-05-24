import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


ConfidenceBucket = Literal["high", "med", "low"]


class LabelingQueueItem(BaseModel):
    """One frame in the review queue, with its review backlog summarized."""

    frame_id: uuid.UUID
    clip_id: uuid.UUID
    clip_filename: str
    clip_created_at: datetime
    frame_index: int
    image_url: str | None
    unreviewed_count: int
    min_confidence: float | None


class PredictedGroup(BaseModel):
    """One bucket of auto-assigned, still-unreviewed detections.

    The group's identity is `(class, predicted_subclass, confidence_bucket)` —
    confirming the predicted sub-class for the whole bucket is the bulk action.
    """

    class_id: uuid.UUID | None
    class_name: str | None
    predicted_subclass_id: uuid.UUID
    predicted_subclass_name: str
    confidence_bucket: ConfidenceBucket
    count: int
    sample_detection_ids: list[uuid.UUID]


class BulkReviewRequest(BaseModel):
    """Apply one of {class change, subclass change, review-flag flip} to many.

    The audit reason is inferred per row exactly as the per-detection PATCH
    does: `user_reassign` when class or subclass changes, `user_review` when
    the reviewed flag flips false → true.
    """

    detection_ids: list[uuid.UUID] = Field(min_length=1, max_length=2000)
    class_id: uuid.UUID | None = None
    subclass_id: uuid.UUID | None = None
    reviewed: bool | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "BulkReviewRequest":
        if not (self.model_fields_set & {"class_id", "subclass_id", "reviewed"}):
            raise ValueError(
                "Provide at least one of class_id, subclass_id, reviewed"
            )
        return self


class BulkReviewResponse(BaseModel):
    updated: int
    skipped: int
    audits_written: int
    affected_frame_ids: list[uuid.UUID]

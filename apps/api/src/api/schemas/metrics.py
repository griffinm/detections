import uuid
from datetime import datetime

from pydantic import BaseModel


class HealthResponse(BaseModel):
    db: str
    redis: str


class AccuracyPoint(BaseModel):
    """One (period, model version) cell of the accuracy time series."""

    period: datetime
    model_version_id: uuid.UUID | None
    n_reviewed: int
    class_top1: float
    subclass_top1: float | None
    mean_confidence: float | None


class ClassMetric(BaseModel):
    class_id: uuid.UUID
    class_name: str
    n_predicted: int
    n_actual: int
    precision: float | None
    recall: float | None


class CalibrationBin(BaseModel):
    bucket: int
    mean_confidence: float
    empirical_accuracy: float
    count: int


class CalibrationResponse(BaseModel):
    bins: list[CalibrationBin]
    ece: float


class MetricsSummary(BaseModel):
    clips: int
    detections: int
    reviewed: int
    pending_review: int
    last7d_class_accuracy: float | None


class TrackAccuracyPoint(BaseModel):
    """One (period, model_version) cell of the track-level accuracy series.

    A track "counts" once it's been reviewed by the user (`tracks.reviewed`).
    Class top-1 = `predicted_class_id` matches the current `class_id`;
    sub-class top-1 = same for `predicted_subclass_id` / `subclass_id`.
    Sub-class accuracy is null when no track in this cell had a sub-class
    prediction yet.
    """

    period: datetime
    model_version_id: uuid.UUID | None
    n_reviewed: int
    class_top1: float
    subclass_top1: float | None
    mean_confidence: float | None


class ReassignmentItem(BaseModel):
    """One row of the 'what changed' panel — a class/sub-class correction."""

    detection_id: uuid.UUID
    frame_id: uuid.UUID | None
    clip_id: uuid.UUID | None
    at: datetime
    reason: str
    from_class: str | None
    to_class: str | None
    from_subclass: str | None
    to_subclass: str | None

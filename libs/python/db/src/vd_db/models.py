import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPKMixin

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

ClipStatus = Enum(
    "pending", "extracting", "detecting", "done", "failed",
    name="clip_status",
)

DetectStatus = Enum(
    "pending", "done", "failed",
    name="detect_status",
)

ClassSource = Enum(
    "builtin", "custom",
    name="class_source",
)

DetSource = Enum(
    "model", "user",
    name="det_source",
)

ModelKind = Enum(
    "yolo", "insightface", "classifier",
    name="model_kind",
)

RunStatus = Enum(
    "queued", "running", "succeeded", "failed", "cancelled",
    name="run_status",
)

AuditReason = Enum(
    "initial_prediction", "user_review", "user_reassign", "user_delete", "retrain_reassign",
    name="audit_reason",
)

DeliveryStatus = Enum(
    "pending", "delivered", "failed",
    name="delivery_status",
)

TrackSource = Enum(
    "tracker", "user",
    name="track_source",
)

TrackAuditReason = Enum(
    "initial", "user_reassign", "user_review",
    "user_split", "user_merge", "user_delete",
    name="track_audit_reason",
)


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

class Class(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "classes"

    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    source: Mapped[str] = mapped_column(ClassSource, nullable=False)
    yolo_class_index: Mapped[int | None] = mapped_column(Integer)
    color_hex: Mapped[str] = mapped_column(Text, nullable=False, server_default="#888888")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    subclasses: Mapped[list["Subclass"]] = relationship(back_populates="class_")


class Subclass(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "subclasses"
    __table_args__ = (UniqueConstraint("class_id", "name"),)

    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classes.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    color_hex: Mapped[str] = mapped_column(Text, nullable=False, server_default="#888888")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    class_: Mapped["Class"] = relationship(back_populates="subclasses")
    examples: Mapped[list["SubclassExample"]] = relationship(back_populates="subclass")


class ModelVersion(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "model_versions"

    kind: Mapped[str] = mapped_column(ModelKind, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    weights_path: Mapped[str] = mapped_column(Text, nullable=False)
    target_class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classes.id", ondelete="SET NULL")
    )
    trained_on: Mapped[int | None] = mapped_column(Integer)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class Clip(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "clips"

    filename: Mapped[str] = mapped_column(Text, nullable=False)
    original_path: Mapped[str] = mapped_column(Text, nullable=False)
    final_path: Mapped[str | None] = mapped_column(Text)
    # Nullable: an externally-submitted job (POST /api/jobs) creates the row
    # before the file is hashed — the worker fills sha256 in during ingest.
    # Postgres lets a UNIQUE column hold multiple NULLs, so dedup still holds.
    sha256: Mapped[str | None] = mapped_column(Text, unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_sec: Mapped[float | None] = mapped_column(Numeric(10, 3))
    fps: Mapped[float | None] = mapped_column(Numeric(6, 3))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    codec: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        ClipStatus, nullable=False, server_default="pending"
    )
    error: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # External job submission (spec 04 §Jobs). 'watch' for folder-watcher drops.
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="watch")
    external_id: Mapped[str | None] = mapped_column(Text)
    callback_url: Mapped[str | None] = mapped_column(Text)
    external_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Set when this clip's bytes duplicate an earlier clip; job results and
    # callbacks resolve through it. Self-FK, SET NULL so deleting the canonical
    # clip never orphans-cascade this row away.
    canonical_clip_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clips.id", ondelete="SET NULL")
    )

    frames: Mapped[list["Frame"]] = relationship(back_populates="clip")


class Frame(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "frames"
    __table_args__ = (UniqueConstraint("clip_id", "frame_index"),)

    clip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clips.id", ondelete="CASCADE"), nullable=False
    )
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp_sec: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    path: Mapped[str | None] = mapped_column(Text)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    phash: Mapped[bytes | None] = mapped_column()
    kept: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    detect_status: Mapped[str] = mapped_column(
        DetectStatus, nullable=False, server_default="pending"
    )

    clip: Mapped["Clip"] = relationship(back_populates="frames")
    detections: Mapped[list["DetectionModel"]] = relationship(back_populates="frame")


class DetectionModel(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "detections"
    __table_args__ = (
        CheckConstraint(
            "bbox ? 'x' AND bbox ? 'y' AND bbox ? 'w' AND bbox ? 'h'",
            name="bbox_shape",
        ),
    )

    frame_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("frames.id", ondelete="CASCADE"), nullable=False
    )
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classes.id", ondelete="SET NULL")
    )
    subclass_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subclasses.id", ondelete="SET NULL")
    )
    bbox: Mapped[dict[str, float]] = mapped_column(JSONB, nullable=False)
    confidence_class: Mapped[float | None] = mapped_column()
    confidence_subclass: Mapped[float | None] = mapped_column()
    source: Mapped[str] = mapped_column(DetSource, nullable=False)
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_versions.id", ondelete="SET NULL")
    )
    predicted_class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classes.id", ondelete="SET NULL")
    )
    predicted_subclass_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subclasses.id", ondelete="SET NULL")
    )
    reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    face_embedding: Mapped[Any | None] = mapped_column(Vector(512))
    object_embedding: Mapped[Any | None] = mapped_column(Vector(768))
    track_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tracks.id", ondelete="SET NULL")
    )

    frame: Mapped["Frame"] = relationship(back_populates="detections")
    track: Mapped["Track | None"] = relationship(back_populates="detections")
    examples: Mapped[list["SubclassExample"]] = relationship(back_populates="detection")
    audits: Mapped[list["DetectionAudit"]] = relationship(back_populates="detection")


class Track(Base, UUIDPKMixin, TimestampMixin):
    """A sequence of detections believed to be the same physical object within
    one clip (BoT-SORT). Sub-class assignment votes across track members
    instead of running per-detection — see `vd.assign_track_subclass`.
    """

    __tablename__ = "tracks"

    clip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clips.id", ondelete="CASCADE"), nullable=False
    )
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classes.id", ondelete="SET NULL")
    )
    subclass_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subclasses.id", ondelete="SET NULL")
    )
    predicted_class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classes.id", ondelete="SET NULL")
    )
    predicted_subclass_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subclasses.id", ondelete="SET NULL")
    )
    confidence_class: Mapped[float | None] = mapped_column()
    confidence_subclass: Mapped[float | None] = mapped_column()
    n_detections: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    first_frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    last_frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(TrackSource, nullable=False)
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_versions.id", ondelete="SET NULL")
    )
    reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    detections: Mapped[list["DetectionModel"]] = relationship(back_populates="track")
    audits: Mapped[list["TrackAudit"]] = relationship(back_populates="track")


class TrackAudit(Base, TimestampMixin):
    """Track-shape ledger: split / merge / reassign / review / delete.

    Per-detection class/subclass propagation from a track PATCH still writes
    `detection_audits` rows with the existing reasons; this table records the
    track-level event itself plus split/merge linkage.
    """

    __tablename__ = "track_audits"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    track_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    reason: Mapped[str] = mapped_column(TrackAuditReason, nullable=False)
    from_class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classes.id", ondelete="SET NULL")
    )
    to_class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classes.id", ondelete="SET NULL")
    )
    from_subclass_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subclasses.id", ondelete="SET NULL")
    )
    to_subclass_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subclasses.id", ondelete="SET NULL")
    )
    # No FKs: a split/merge audit may reference a track that's since been
    # soft-deleted, and we still want the audit row to resolve.
    from_track_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    to_track_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    pivot_frame_index: Mapped[int | None] = mapped_column(Integer)
    n_detections_moved: Mapped[int | None] = mapped_column(Integer)
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_versions.id", ondelete="SET NULL")
    )

    track: Mapped["Track"] = relationship(back_populates="audits")


class SubclassExample(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "subclass_examples"
    __table_args__ = (UniqueConstraint("subclass_id", "detection_id"),)

    subclass_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subclasses.id", ondelete="CASCADE"), nullable=False
    )
    detection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("detections.id", ondelete="CASCADE"), nullable=False
    )
    starred: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    subclass: Mapped["Subclass"] = relationship(back_populates="examples")
    detection: Mapped["DetectionModel"] = relationship(back_populates="examples")


class TrainingRun(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "training_runs"

    kind: Mapped[str] = mapped_column(ModelKind, nullable=False)
    target_class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classes.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(RunStatus, nullable=False, server_default="queued")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    log_path: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)


class DetectionAudit(Base, TimestampMixin):
    __tablename__ = "detection_audits"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    detection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("detections.id", ondelete="CASCADE"), nullable=False
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    from_class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classes.id", ondelete="SET NULL")
    )
    to_class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classes.id", ondelete="SET NULL")
    )
    from_subclass_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subclasses.id", ondelete="SET NULL")
    )
    to_subclass_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subclasses.id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(AuditReason, nullable=False)
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_versions.id", ondelete="SET NULL")
    )

    detection: Mapped["DetectionModel"] = relationship(back_populates="audits")


class SettingsKV(Base):
    __tablename__ = "settings_kv"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)


class WebhookDelivery(Base, UUIDPKMixin, TimestampMixin):
    """Outbound-callback ledger for externally-submitted jobs (spec 03).

    One row per `(clip_id, event)` — `vd.deliver_callback` upserts on that key,
    so a redelivered event is the same row and a `delivered` row is never
    re-sent. Persisting it survives a worker restart and is inspectable when a
    submitter claims it never heard back.
    """

    __tablename__ = "webhook_deliveries"
    __table_args__ = (UniqueConstraint("clip_id", "event"),)

    clip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clips.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    event: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        DeliveryStatus, nullable=False, server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_status: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

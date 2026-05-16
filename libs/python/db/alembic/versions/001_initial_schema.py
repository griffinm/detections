"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Pre-built references to existing types (create_type=False)
_clip_status = postgresql.ENUM(
    "pending", "extracting", "detecting", "done", "failed",
    name="clip_status", create_type=False,
)
_detect_status = postgresql.ENUM(
    "pending", "done", "failed",
    name="detect_status", create_type=False,
)
_class_source = postgresql.ENUM(
    "builtin", "custom",
    name="class_source", create_type=False,
)
_det_source = postgresql.ENUM(
    "model", "user",
    name="det_source", create_type=False,
)
_model_kind = postgresql.ENUM(
    "yolo", "insightface", "classifier",
    name="model_kind", create_type=False,
)
_run_status = postgresql.ENUM(
    "queued", "running", "succeeded", "failed", "cancelled",
    name="run_status", create_type=False,
)
_audit_reason = postgresql.ENUM(
    "initial_prediction", "user_review", "user_reassign", "user_delete", "retrain_reassign",
    name="audit_reason", create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()

    # Extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # Enums — create once via raw SQL
    bind.execute(sa.text(
        "CREATE TYPE clip_status AS ENUM ('pending','extracting','detecting','done','failed')"
    ))
    bind.execute(sa.text(
        "CREATE TYPE detect_status AS ENUM ('pending','done','failed')"
    ))
    bind.execute(sa.text(
        "CREATE TYPE class_source AS ENUM ('builtin','custom')"
    ))
    bind.execute(sa.text(
        "CREATE TYPE det_source AS ENUM ('model','user')"
    ))
    bind.execute(sa.text(
        "CREATE TYPE model_kind AS ENUM ('yolo','insightface','classifier')"
    ))
    bind.execute(sa.text(
        "CREATE TYPE run_status AS ENUM ('queued','running','succeeded','failed','cancelled')"
    ))
    bind.execute(sa.text(
        "CREATE TYPE audit_reason AS ENUM "
        "('initial_prediction','user_review','user_reassign','user_delete','retrain_reassign')"
    ))

    # classes (no FK deps)
    op.create_table(
        "classes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("source", _class_source, nullable=False),
        sa.Column("yolo_class_index", sa.Integer()),
        sa.Column("color_hex", sa.Text(), nullable=False, server_default="#888888"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("name"),
    )

    # subclasses
    op.create_table(
        "subclasses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("class_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("classes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("color_hex", sa.Text(), nullable=False, server_default="#888888"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("class_id", "name"),
    )

    # model_versions
    op.create_table(
        "model_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", _model_kind, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("weights_path", sa.Text(), nullable=False),
        sa.Column("target_class_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("classes.id", ondelete="SET NULL")),
        sa.Column("trained_on", sa.Integer()),
        sa.Column("metrics", postgresql.JSONB()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # clips
    op.create_table(
        "clips",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("original_path", sa.Text(), nullable=False),
        sa.Column("final_path", sa.Text()),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("duration_sec", sa.Numeric(10, 3)),
        sa.Column("fps", sa.Numeric(6, 3)),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("codec", sa.Text()),
        sa.Column("status", _clip_status, nullable=False, server_default="pending"),
        sa.Column("error", sa.Text()),
        sa.Column("ingested_at", sa.DateTime(timezone=True)),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("sha256"),
    )

    # frames
    op.create_table(
        "frames",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("clip_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clips.id", ondelete="CASCADE"), nullable=False),
        sa.Column("frame_index", sa.Integer(), nullable=False),
        sa.Column("timestamp_sec", sa.Numeric(10, 3), nullable=False),
        sa.Column("path", sa.Text()),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("phash", sa.LargeBinary()),
        sa.Column("kept", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("detect_status", _detect_status, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("clip_id", "frame_index"),
    )

    # detections — vector columns added separately to avoid pgvector import at module level
    op.create_table(
        "detections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("frame_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("frames.id", ondelete="CASCADE"), nullable=False),
        sa.Column("class_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("classes.id", ondelete="SET NULL")),
        sa.Column("subclass_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("subclasses.id", ondelete="SET NULL")),
        sa.Column("bbox", postgresql.JSONB(), nullable=False),
        sa.Column("confidence_class", sa.Float()),
        sa.Column("confidence_subclass", sa.Float()),
        sa.Column("source", _det_source, nullable=False),
        sa.Column("model_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("model_versions.id", ondelete="SET NULL")),
        sa.Column("predicted_class_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("classes.id", ondelete="SET NULL")),
        sa.Column("predicted_subclass_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("subclasses.id", ondelete="SET NULL")),
        sa.Column("reviewed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "bbox ? 'x' AND bbox ? 'y' AND bbox ? 'w' AND bbox ? 'h'",
            name="bbox_shape",
        ),
    )
    # Add vector columns via raw SQL (pgvector)
    op.execute("ALTER TABLE detections ADD COLUMN face_embedding vector(512)")
    op.execute("ALTER TABLE detections ADD COLUMN object_embedding vector(768)")

    # subclass_examples
    op.create_table(
        "subclass_examples",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subclass_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("subclasses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("detection_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("detections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("starred", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("subclass_id", "detection_id"),
    )

    # training_runs
    op.create_table(
        "training_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", _model_kind, nullable=False),
        sa.Column("target_class_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("classes.id", ondelete="SET NULL")),
        sa.Column("status", _run_status, nullable=False, server_default="queued"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("metrics", postgresql.JSONB()),
        sa.Column("log_path", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # detection_audits (bigserial PK)
    op.create_table(
        "detection_audits",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("detection_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("detections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("from_class_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("classes.id", ondelete="SET NULL")),
        sa.Column("to_class_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("classes.id", ondelete="SET NULL")),
        sa.Column("from_subclass_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("subclasses.id", ondelete="SET NULL")),
        sa.Column("to_subclass_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("subclasses.id", ondelete="SET NULL")),
        sa.Column("reason", _audit_reason, nullable=False),
        sa.Column("model_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("model_versions.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # settings_kv
    op.create_table(
        "settings_kv",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
    )

    # Scalar indexes
    op.create_index("ix_clips_status", "clips", ["status"])
    op.create_index("ix_clips_ingested_at", "clips", [sa.text("ingested_at DESC")])
    op.create_index("ix_frames_clip_id_frame_index", "frames", ["clip_id", "frame_index"])
    op.create_index("ix_frames_detect_status", "frames", ["detect_status"])
    op.create_index("ix_frames_kept", "frames", ["kept"], postgresql_where=sa.text("kept = true"))
    op.create_index("ix_detections_frame_id", "detections", ["frame_id"])
    op.create_index("ix_detections_class_reviewed", "detections", ["class_id", "reviewed"])

    # HNSW vector indexes
    op.execute(
        "CREATE INDEX ix_detections_face_embedding ON detections "
        "USING hnsw (face_embedding vector_cosine_ops) "
        "WHERE face_embedding IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_detections_object_embedding ON detections "
        "USING hnsw (object_embedding vector_cosine_ops) "
        "WHERE object_embedding IS NOT NULL"
    )

    # Seed builtin classes
    op.execute(sa.text("""
        INSERT INTO classes (id, name, source, color_hex, is_active)
        VALUES
          (gen_random_uuid(), 'person', 'builtin', '#ef4444', true),
          (gen_random_uuid(), 'car',    'builtin', '#3b82f6', true),
          (gen_random_uuid(), 'dog',    'builtin', '#f59e0b', true),
          (gen_random_uuid(), 'bear',   'builtin', '#8b5cf6', true)
    """))


def downgrade() -> None:
    op.drop_table("settings_kv")
    op.drop_table("detection_audits")
    op.drop_table("training_runs")
    op.drop_table("subclass_examples")
    op.drop_table("detections")
    op.drop_table("frames")
    op.drop_table("clips")
    op.drop_table("model_versions")
    op.drop_table("subclasses")
    op.drop_table("classes")

    for name in ("clip_status", "detect_status", "class_source", "det_source",
                 "model_kind", "run_status", "audit_reason"):
        op.execute(sa.text(f"DROP TYPE IF EXISTS {name}"))

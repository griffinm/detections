"""Per-clip object tracks

Revision ID: 006
Revises: 005
Create Date: 2026-05-27

Introduces `tracks` — sequences of detections believed to be the same physical
object within one clip. `detections.track_id` becomes a nullable FK; pre-006
detections stay NULL, and a tracker-dropped single-frame box also stays NULL.

Tracks aggregate per-detection embeddings into a single sub-class vote
(`vd.assign_track_subclass`), which is more robust at 1 fps than per-frame
kNN. The labeling UI is still detection-based at this point; Stage B will add
the track UI + split/merge.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_track_source = postgresql.ENUM(
    "tracker", "user",
    name="track_source", create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "CREATE TYPE track_source AS ENUM ('tracker','user')"
    ))

    op.create_table(
        "tracks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "clip_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clips.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "class_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("classes.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "subclass_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subclasses.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "predicted_class_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("classes.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "predicted_subclass_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subclasses.id", ondelete="SET NULL"),
        ),
        sa.Column("confidence_class", sa.Float()),
        sa.Column("confidence_subclass", sa.Float()),
        sa.Column("n_detections", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_frame_index", sa.Integer(), nullable=False),
        sa.Column("last_frame_index", sa.Integer(), nullable=False),
        sa.Column("source", _track_source, nullable=False),
        sa.Column(
            "model_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("model_versions.id", ondelete="SET NULL"),
        ),
        sa.Column("reviewed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_tracks_clip_id_first_frame",
        "tracks",
        ["clip_id", "first_frame_index"],
    )
    op.create_index(
        "ix_tracks_class_reviewed",
        "tracks",
        ["class_id", "reviewed"],
    )
    op.create_index(
        "ix_tracks_live",
        "tracks",
        ["clip_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.add_column(
        "detections",
        sa.Column(
            "track_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tracks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_detections_track_id",
        "detections",
        ["track_id"],
        postgresql_where=sa.text("track_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_detections_track_id", table_name="detections")
    op.drop_column("detections", "track_id")
    op.drop_index("ix_tracks_live", table_name="tracks")
    op.drop_index("ix_tracks_class_reviewed", table_name="tracks")
    op.drop_index("ix_tracks_clip_id_first_frame", table_name="tracks")
    op.drop_table("tracks")
    op.execute(sa.text("DROP TYPE IF EXISTS track_source"))

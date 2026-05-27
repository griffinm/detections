"""Track audit ledger

Revision ID: 007
Revises: 006
Create Date: 2026-05-27

Track-shape events — split, merge, reassign, review, delete — get their own
ledger. Per-detection effects (class/subclass propagation from a track PATCH)
still flow through `detection_audits` with the existing reasons; the
`audit_reason` enum is intentionally not extended.

`initial` is emitted by `vd.detect_and_track_clip` so the ledger has a "first
seen" row per track, useful for `MIN(at)` queries without scanning detections.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_track_audit_reason = postgresql.ENUM(
    "initial", "user_reassign", "user_review",
    "user_split", "user_merge", "user_delete",
    name="track_audit_reason", create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "CREATE TYPE track_audit_reason AS ENUM "
        "('initial','user_reassign','user_review','user_split','user_merge','user_delete')"
    ))

    op.create_table(
        "track_audits",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "track_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tracks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("reason", _track_audit_reason, nullable=False),
        sa.Column(
            "from_class_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("classes.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "to_class_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("classes.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "from_subclass_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subclasses.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "to_subclass_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subclasses.id", ondelete="SET NULL"),
        ),
        # No FK on from/to_track_id — split/merge may reference a track that's
        # since been soft-deleted, and we still want the audit to resolve.
        sa.Column("from_track_id", postgresql.UUID(as_uuid=True)),
        sa.Column("to_track_id", postgresql.UUID(as_uuid=True)),
        sa.Column("pivot_frame_index", sa.Integer()),
        sa.Column("n_detections_moved", sa.Integer()),
        sa.Column(
            "model_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("model_versions.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_track_audits_track_id_at_desc",
        "track_audits",
        ["track_id", sa.text("at DESC")],
    )
    op.create_index("ix_track_audits_reason", "track_audits", ["reason"])


def downgrade() -> None:
    op.drop_index("ix_track_audits_reason", table_name="track_audits")
    op.drop_index("ix_track_audits_track_id_at_desc", table_name="track_audits")
    op.drop_table("track_audits")
    op.execute(sa.text("DROP TYPE IF EXISTS track_audit_reason"))

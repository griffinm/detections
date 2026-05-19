"""External job submission

Revision ID: 004
Revises: 003
Create Date: 2026-05-18

`POST /api/jobs` lets upstream apps submit videos by path reference and get the
detection result back via webhook. This adds the correlation + callback columns
to `clips` and the `webhook_deliveries` callback ledger.

`clips.sha256` becomes nullable: a job row is created by the API before the
worker hashes the file. Postgres allows multiple NULLs under a UNIQUE column,
so content dedup still holds once the worker fills the hash in.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_delivery_status = postgresql.ENUM(
    "pending", "delivered", "failed",
    name="delivery_status", create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "CREATE TYPE delivery_status AS ENUM ('pending','delivered','failed')"
    ))

    op.alter_column("clips", "sha256", nullable=True)
    op.add_column(
        "clips",
        sa.Column("source", sa.Text(), nullable=False, server_default="watch"),
    )
    op.add_column("clips", sa.Column("external_id", sa.Text()))
    op.add_column("clips", sa.Column("callback_url", sa.Text()))
    op.add_column("clips", sa.Column("external_metadata", postgresql.JSONB()))
    op.add_column(
        "clips",
        sa.Column(
            "canonical_clip_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clips.id", ondelete="SET NULL"),
        ),
    )
    op.create_index(
        "ix_clips_source_external_id",
        "clips",
        ["source", "external_id"],
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "clip_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clips.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("status", _delivery_status, nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("response_status", sa.Integer()),
        sa.Column("last_error", sa.Text()),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("clip_id", "event"),
    )
    op.create_index("ix_webhook_deliveries_clip_id", "webhook_deliveries", ["clip_id"])
    op.create_index(
        "ix_webhook_deliveries_pending",
        "webhook_deliveries",
        ["status"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_table("webhook_deliveries")
    op.drop_index("ix_clips_source_external_id", table_name="clips")
    op.drop_column("clips", "canonical_clip_id")
    op.drop_column("clips", "external_metadata")
    op.drop_column("clips", "callback_url")
    op.drop_column("clips", "external_id")
    op.drop_column("clips", "source")
    op.alter_column("clips", "sha256", nullable=False)
    op.execute(sa.text("DROP TYPE IF EXISTS delivery_status"))

"""Soft-delete column for detections

Revision ID: 003
Revises: 002
Create Date: 2026-05-15

Detections are soft-deleted (`deleted_at` set) rather than hard-deleted, so a
`user_delete` row survives in `detection_audits` — the ledger FK is
`ON DELETE CASCADE`, which would otherwise erase it. Reads filter
`deleted_at IS NULL`.

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "detections",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("detections", "deleted_at")

"""Composite keyset index on training_runs

Revision ID: 005
Revises: 004
Create Date: 2026-05-23

Cursor pagination on `GET /api/training-runs` keysets on
`(created_at, id)` DESC (see `apps/api/src/api/utils/pagination.py`).
UUID v7 PKs are naturally time-sorted so `id` would carry most of the
ordering on its own, but the explicit composite documents the intent and
lets the planner do an index-only scan for the row-value comparison
`WHERE (created_at, id) < ($v, $i)`.

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_training_runs_created_at_id_desc",
        "training_runs",
        [sa.text("created_at DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_training_runs_created_at_id_desc", table_name="training_runs")

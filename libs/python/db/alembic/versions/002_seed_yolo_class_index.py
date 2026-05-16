"""Seed yolo_class_index for builtin classes

Revision ID: 002
Revises: 001
Create Date: 2026-05-15

Maps the four builtin classes to their COCO/YOLOv11 class indices so the
detection task can resolve a YOLO class index back to a `classes` row.

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# COCO class indices (shared by all YOLOv11 COCO-pretrained checkpoints).
_COCO_INDEX = {"person": 0, "car": 2, "dog": 16, "bear": 21}


def upgrade() -> None:
    for name, index in _COCO_INDEX.items():
        op.execute(
            sa.text("UPDATE classes SET yolo_class_index = :idx WHERE name = :name").bindparams(
                idx=index, name=name
            )
        )


def downgrade() -> None:
    for name in _COCO_INDEX:
        op.execute(
            sa.text("UPDATE classes SET yolo_class_index = NULL WHERE name = :name").bindparams(
                name=name
            )
        )

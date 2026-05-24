import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid7() -> uuid.UUID:
    try:
        import uuid_utils  # type: ignore[import-untyped]

        return uuid.UUID(str(uuid_utils.uuid7()))
    except ImportError:
        return uuid.uuid4()


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UUIDPKMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=_uuid7,
    )

"""DB-backed runtime overrides for the env-driven `Settings`.

`settings_kv` rows overlay env defaults so the owner can retune the running
system from the `/settings` page without restarting any process. Only
`OVERRIDABLE_KEYS` may be set; values are stored already coerced to the field
type by the API, so a plain `model_copy` is enough to apply them.
"""

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from vd_settings import OVERRIDABLE_KEYS, Settings

from .models import SettingsKV


async def get_overrides(session: AsyncSession) -> dict[str, Any]:
    """Return all stored overrides, restricted to currently-overridable keys."""
    rows = await session.execute(select(SettingsKV.key, SettingsKV.value))
    return {k: v for k, v in rows.all() if k in OVERRIDABLE_KEYS}


async def load_effective_settings(session: AsyncSession) -> Settings:
    """`Settings` with `settings_kv` overrides applied over the env defaults."""
    overrides = await get_overrides(session)
    base = Settings()
    return base.model_copy(update=overrides) if overrides else base


async def set_override(session: AsyncSession, key: str, value: Any) -> None:
    """Upsert a single override row and commit."""
    stmt = pg_insert(SettingsKV).values(key=key, value=value)
    stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": value})
    await session.execute(stmt)
    await session.commit()


async def clear_override(session: AsyncSession, key: str) -> None:
    """Delete a single override row (reset to the env default) and commit."""
    await session.execute(delete(SettingsKV).where(SettingsKV.key == key))
    await session.commit()

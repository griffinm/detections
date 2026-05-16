from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas.settings import SettingItem, SettingUpdate
from vd_db import clear_override, load_effective_settings, set_override
from vd_settings import OVERRIDABLE_KEYS, Settings

router = APIRouter(prefix="/settings", tags=["settings"])

# Env defaults, resolved once — the baseline a reset returns to.
_DEFAULTS = Settings()


def _field_type(key: str) -> str:
    ann = Settings.model_fields[key].annotation
    if ann is bool:  # bool is a subclass of int — check it first
        return "boolean"
    if ann is int:
        return "integer"
    return "number"


def _item(key: str, effective: Settings) -> SettingItem:
    return SettingItem(
        key=key,
        value=getattr(effective, key),
        default=getattr(_DEFAULTS, key),
        type=_field_type(key),
    )


def _require_overridable(key: str) -> None:
    if key not in OVERRIDABLE_KEYS:
        raise HTTPException(
            status_code=404, detail=f"Unknown or non-overridable setting: {key}"
        )


@router.get("", response_model=list[SettingItem])
async def list_settings(db: AsyncSession = Depends(get_db)) -> list[SettingItem]:
    effective = await load_effective_settings(db)
    return [_item(k, effective) for k in OVERRIDABLE_KEYS]


@router.put("/{key}", response_model=SettingItem)
async def put_setting(
    key: str, body: SettingUpdate, db: AsyncSession = Depends(get_db)
) -> SettingItem:
    _require_overridable(key)
    try:
        # Re-validate against the field's type/constraints, then store the
        # coerced value so the runtime override layer can apply it as-is.
        validated = Settings(**{key: body.value})
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from exc
    await set_override(db, key, getattr(validated, key))
    return _item(key, await load_effective_settings(db))


@router.delete("/{key}", response_model=SettingItem)
async def reset_setting(key: str, db: AsyncSession = Depends(get_db)) -> SettingItem:
    _require_overridable(key)
    await clear_override(db, key)
    return _item(key, await load_effective_settings(db))

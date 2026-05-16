from typing import Any, Literal

from pydantic import BaseModel


class SettingItem(BaseModel):
    """One overridable setting: its effective value and the env default."""

    key: str
    value: Any
    default: Any
    type: Literal["number", "integer", "boolean"]


class SettingUpdate(BaseModel):
    value: Any

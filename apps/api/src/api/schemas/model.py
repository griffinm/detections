import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ModelVersionRead(BaseModel):
    id: uuid.UUID
    kind: str
    name: str
    weights_path: str
    target_class_id: uuid.UUID | None
    trained_on: int | None
    metrics: dict[str, Any] | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}

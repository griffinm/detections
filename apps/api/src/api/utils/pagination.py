"""Cursor-based pagination — the canonical helper for list endpoints.

Implements the contract in `specs/04-backend-api.md`:

  Request   ?cursor=<opaque>&limit=<int>  (default 50, max 200)
  Response  Paginated[T] = { items, total, next_cursor }
  Ordering  always (sort_col, id) DESC, with the id as a stable tiebreaker
  Cursor    opaque to consumers; encodes (sort_value, id) for keyset paging

Routes consume `cursor_params` as a FastAPI dependency, then call
`apply_keyset` to add the WHERE clause and `build_page` to assemble the
response envelope from the over-fetched rows.

The helper is intentionally parameterized over `(sort_col, id_col)` so it
generalizes to any resource sorted by a (timestamp, uuid) keyset, not just
`(created_at, id)`.
"""

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

from fastapi import HTTPException, Query
from sqlalchemy import ColumnElement, Select, tuple_

from api.schemas.common import Paginated

T = TypeVar("T")

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


@dataclass(frozen=True)
class CursorPage:
    """Parsed (cursor, limit) — threaded into `apply_keyset` and `build_page`."""

    cursor: str | None
    limit: int


def cursor_params(
    cursor: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
) -> CursorPage:
    return CursorPage(cursor=cursor, limit=limit)


def encode_cursor(sort_value: Any, id_value: uuid.UUID) -> str:
    """Base64-url-safe JSON; the format is opaque and may change without notice."""
    if isinstance(sort_value, datetime):
        encoded_value: Any = sort_value.isoformat()
    else:
        encoded_value = sort_value
    raw = json.dumps(
        {"v": encoded_value, "i": str(id_value)}, separators=(",", ":")
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[Any, uuid.UUID] | None:
    """Decode an opaque cursor → (sort_value, id_value). 400 if malformed.

    Permissive about the row that the cursor points at — if the anchor has
    since been deleted, the keyset still slices "rows strictly older than
    (value, id)" correctly, so paging continues without a gap.
    """
    if cursor is None:
        return None
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
        sort_raw = payload["v"]
        id_value = uuid.UUID(payload["i"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Malformed cursor") from exc

    sort_value: Any
    if isinstance(sort_raw, str):
        try:
            sort_value = datetime.fromisoformat(sort_raw)
        except ValueError:
            sort_value = sort_raw
    else:
        sort_value = sort_raw
    return sort_value, id_value


def apply_keyset(
    query: Select,
    sort_col: ColumnElement,
    id_col: ColumnElement,
    cursor: str | None,
    *,
    direction: str = "desc",
) -> Select:
    """Add the keyset WHERE + ORDER BY clauses for cursor pagination.

    For `direction='desc'`, emits `(sort_col, id) < (cursor_value, cursor_id)`
    and `ORDER BY sort_col DESC, id DESC` — the row-value comparison is the
    Postgres-native form that pairs with a composite `(sort_col DESC, id DESC)`
    btree for keyset performance.

    Caller should `.limit(page.limit + 1)` on the returned query so
    `build_page` can detect whether a next page exists.
    """
    decoded = decode_cursor(cursor)
    if direction == "desc":
        order = (sort_col.desc(), id_col.desc())
        if decoded is not None:
            anchor_value, anchor_id = decoded
            query = query.where(
                tuple_(sort_col, id_col) < tuple_(anchor_value, anchor_id)
            )
    else:
        order = (sort_col.asc(), id_col.asc())
        if decoded is not None:
            anchor_value, anchor_id = decoded
            query = query.where(
                tuple_(sort_col, id_col) > tuple_(anchor_value, anchor_id)
            )
    return query.order_by(*order)


def build_page(
    rows: list[Any],
    *,
    sort_attr: str,
    id_attr: str,
    limit: int,
    total: int,
    item_cls: type | None = None,
) -> Paginated:
    """Pop the over-fetched row, derive `next_cursor`, assemble the envelope.

    `rows` is what the keyset query returned (over-fetched by 1 via
    `.limit(limit + 1)`). If we got `limit + 1` rows, the extra one is dropped
    and its predecessor's `(sort_attr, id_attr)` becomes `next_cursor`.
    """
    has_more = len(rows) > limit
    visible = rows[:limit] if has_more else rows
    next_cursor: str | None = None
    if has_more and visible:
        last = visible[-1]
        next_cursor = encode_cursor(getattr(last, sort_attr), getattr(last, id_attr))

    items = (
        [item_cls.model_validate(r) for r in visible] if item_cls is not None else visible
    )
    return Paginated(items=items, total=total, next_cursor=next_cursor)


def offset_from_cursor(cursor: str | None) -> int:
    """Decode an opaque offset cursor → int. 400 if malformed.

    Used by endpoints where keyset pagination is awkward — e.g. the detection
    gallery sorts by `(reviewed_at NULLS LAST, created_at)`, which a single
    `(sort_col, id)` keyset can't express without losing NULL semantics. The
    trade-off is that offset pagination can show duplicates if rows are
    inserted between page fetches; acceptable for admin galleries.
    """
    if cursor is None:
        return 0
    try:
        offset = int(cursor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Malformed cursor") from exc
    if offset < 0:
        raise HTTPException(status_code=400, detail="Malformed cursor")
    return offset


def offset_page(
    items: list[Any],
    *,
    offset: int,
    limit: int,
    total: int,
) -> Paginated:
    """Build a `Paginated` envelope from a pre-sliced `items` list + total.

    Mirror of `build_page` for offset-based pagination. Caller has already
    applied `.offset(offset).limit(limit)` to its query.
    """
    has_more = offset + len(items) < total
    next_cursor = str(offset + limit) if has_more else None
    return Paginated(items=items, total=total, next_cursor=next_cursor)

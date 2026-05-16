# 04 — Backend API

## Stack

- **FastAPI** with **`uvicorn`** in dev (gunicorn + uvicorn workers in prod).
- **SQLAlchemy 2.x async** via `asyncpg`.
- **Pydantic v2** models (request/response).
- **`fastapi-pagination`** for cursor pagination on list endpoints.
- **SSE** (server-sent events) for live processing progress (simpler than
  WebSockets, and we only need server→client).
- Configuration via `libs/python/settings.Settings`.

The API does NOT enqueue heavy work itself — it writes to the DB and pushes
Celery tasks to Redis. The worker plan (05) covers task semantics.

## Project layout

```
apps/api/
├── pyproject.toml
├── src/
│   └── api/
│       ├── __init__.py
│       ├── main.py                    # FastAPI app factory + lifespan
│       ├── deps.py                    # dependencies (db session, settings)
│       ├── routers/
│       │   ├── clips.py
│       │   ├── frames.py
│       │   ├── detections.py
│       │   ├── classes.py
│       │   ├── subclasses.py
│       │   ├── labeling.py            # review queue, bulk ops
│       │   ├── models.py              # model versions, trigger training
│       │   ├── metrics.py             # accuracy-over-time
│       │   ├── settings.py            # tunable settings
│       │   ├── system.py              # health, queue stats
│       │   └── stream.py              # SSE
│       ├── schemas/
│       │   ├── clip.py
│       │   ├── frame.py
│       │   ├── detection.py
│       │   ├── class_.py
│       │   ├── metrics.py
│       │   └── common.py              # pagination, error envelope
│       ├── services/                  # business logic (DB + tasks)
│       │   ├── clip_service.py
│       │   ├── detection_service.py
│       │   ├── labeling_service.py
│       │   └── training_service.py
│       └── static/                    # serves /data/frames/* via StaticFiles
└── tests/
```

## App factory

```python
# apps/api/src/api/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from .deps import settings, engine
from .routers import (clips, frames, detections, classes, subclasses,
                      labeling, models, metrics, settings as settings_r,
                      system, stream)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # warm DB pool, register SSE pubsub, etc.
    yield
    await engine.dispose()

def create_app() -> FastAPI:
    app = FastAPI(title="video-detection", lifespan=lifespan)
    app.mount("/files/frames", StaticFiles(directory=settings.frames_dir), name="frames")
    for r in (clips, frames, detections, classes, subclasses, labeling,
              models, metrics, settings_r, system, stream):
        app.include_router(r.router, prefix="/api")
    return app

app = create_app()
```

## Dependency wiring

```python
# apps/api/src/api/deps.py
from collections.abc import AsyncIterator
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
from vd_settings import Settings

settings = Settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session

async def get_celery():
    # lazy import to avoid pulling celery into the API process startup path
    from vd_tasks.app import celery_app
    return celery_app
```

## Endpoint catalog

All paths prefixed with `/api`. Pagination is cursor-based (`?cursor=…&limit=…`).

### Clips
- `GET /clips?status=&q=` — list, paginated.
- `GET /clips/{id}` — detail, includes frame count + detection count.
- `DELETE /clips/{id}` *(Phase 7)* — enqueues `vd.delete_clip`: cascades frames
  + detections, always removes the frame JPEGs, removes the source video iff
  `delete_processed_videos`. Returns 202; UI updates on the `clip.deleted` SSE.
- `POST /clips/{id}/reprocess` — re-enqueue `detect_frame` for all kept frames
  using the active model.

### Frames
- `GET /clips/{id}/frames?kept=true` — paginated.
- `GET /frames/{id}` — detail incl. detections (soft-deleted ones excluded).
- `POST /frames/{id}/review` — mark every unreviewed detection on the frame
  reviewed (the labeling UI's "Save"); writes `user_review` audits. *(Phase 3)*
- `GET /frames/{id}/image` — redirects to `/files/frames/<clip>/<frame>.jpg`.
- `POST /frames/{id}/redetect` — re-run detection (e.g., after model update).

### Detections *(Phase 3)*
- `POST /detections` — user creates a new detection (drew a box):
  `{ frame_id, bbox, class_id, subclass_id? }`. `source='user'`, `reviewed=true`;
  audit `user_reassign`.
- `PATCH /detections/{id}` — update bbox, class, subclass, reviewed. Writes a
  `detection_audits` row for class/subclass changes (`user_reassign`) and
  first review (`user_review`); a bbox-only edit writes none.
- `DELETE /detections/{id}` — soft delete (`deleted_at`); audit `user_delete`.
- `POST /detections/{id}/restore` — clear `deleted_at` (undo affordance).
- `POST /detections/{id}/promote-example` — promotes to `subclass_examples`. *(Phase 4)*
- Detection mutations publish a `frame.updated` SSE event.

### Classes / Subclasses *(subclass endpoints: Phase 4)*
- `GET /classes`, `POST /classes`, `PATCH /classes/{id}`, `DELETE /classes/{id}`.
- `GET /classes/{id}/subclasses`, `POST /classes/{id}/subclasses` — creating
  the *first* active sub-class enqueues `vd.backfill_embeddings`.
- `POST /classes/{id}/rescan-subclasses` — manually re-enqueue
  `vd.backfill_embeddings` for the class (powers the UI re-scan button).
- `GET /subclasses?class_id=`, `GET /subclasses/{id}`, `PATCH /subclasses/{id}`,
  `DELETE /subclasses/{id}` (soft delete via `is_active`).
- `GET /subclasses/{id}/examples` — example gallery (limit-capped list; each
  item carries the detection bbox + frame image URL so the UI crops the
  thumbnail client-side).
- `POST /subclasses/{id}/examples` — add an example; `DELETE …/examples/{id}`.

### Labeling queue
- `GET /labeling/queue?strategy=&class_id=&limit=` — ordered list of frames
  with unreviewed detections. `strategy` ∈ `lowconf` (lowest unreviewed
  `confidence_class` first) | `unreviewed` (newest frame first). The optional
  `class_id` filters to frames with an unreviewed detection of that class and
  scopes the per-frame counts to it. The kNN `recent corrections` strategy is
  deferred (`plans/deferred.md`). The UI holds the returned ordering for
  keyboard (`J`/`K`) navigation.

### Models + training
- `GET /models?kind=` — list versions.
- `POST /models/{id}/activate` — switch active weights.
- `POST /training-runs` — body: `{ kind, target_class_id? }` — enqueues a job.
- `GET /training-runs?status=` — list.
- `GET /training-runs/{id}` — incl. tail of log + metrics.

### Metrics *(Phase 6 — computed on-the-fly, no materialized view)*
- `GET /metrics/accuracy?bucket=day|week&from=&to=&class_id=&model_version_id=`
  — class/sub-class top-1 time series, grouped by `(period, model_version)`.
- `GET /metrics/per-class?model_version_id=` — per-class precision & recall.
- `GET /metrics/calibration?class_id=&model_version_id=` — confidence-decile
  buckets → empirical accuracy, plus ECE.
- `GET /metrics/summary` — dashboard tiles (counts, last 7d accuracy).
- `GET /metrics/changes?limit=` — recent class/sub-class reassignments (the
  "what changed" panel) from `detection_audits`.

### Settings *(Phase 7 — implemented)*
- `GET /settings` — list overridable tunables: effective value, env default, type.
- `PUT /settings/{key}` — validate + upsert a `settings_kv` override.
- `DELETE /settings/{key}` — clear the override (reset to the env default).
- Overrides overlay env defaults via `vd_db.load_effective_settings`, which
  worker/API jobs call per task — edits take effect with no restart. Only the
  `vd_settings.OVERRIDABLE_KEYS` tunables are editable; paths/URLs stay env-only.

### System *(Phase 7 — `disk`/`purge-frames` implemented)*
- `GET /system/health` — DB+Redis+models reachable?
- `GET /system/queue` — celery queue depths via `inspect`. *Deferred* — Flower
  (`:5555`) already covers queue inspection (`plans/deferred.md`).
- `GET /system/disk` — per-directory bytes/file-count + total/free disk.
- `POST /system/purge-frames` — body `{older_than_days}`; enqueues `vd.purge_frames`.

### Stream
- `GET /stream/events` — SSE feed of:
  - `clip.status`, `clip.created`, `clip.done`, `clip.deleted`
  - `frame.detect.done`
  - `frame.updated` (a detection was edited — clip_id, frame_id)
  - `training_run.update`
  - `queue.depth` (periodic)
  Drives the live UI without polling.

## SSE plumbing

The worker publishes events to Redis pub/sub on channel `events:*`. The API's
`/stream/events` endpoint subscribes and re-emits. The frontend hooks
`EventSource` on mount. This avoids long-poll DB queries from the UI.

## Schemas

Conventions:
- Every model has `BaseRead` and `BaseCreate`/`BaseUpdate` variants.
- IDs are strings on the wire (UUID v7).
- Timestamps are ISO 8601 strings.
- Bbox is `{x:number, y:number, w:number, h:number}` normalized 0..1.

Example:
```python
# apps/api/src/api/schemas/detection.py
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field

class Bbox(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)

class DetectionRead(BaseModel):
    id: UUID
    frame_id: UUID
    bbox: Bbox
    class_id: UUID | None
    subclass_id: UUID | None
    confidence_class: float | None
    confidence_subclass: float | None
    source: str
    reviewed: bool
    predicted_class_id: UUID | None
    predicted_subclass_id: UUID | None
    model_version_id: UUID | None
    created_at: datetime
    updated_at: datetime

class DetectionUpdate(BaseModel):
    bbox: Bbox | None = None
    class_id: UUID | None = None
    subclass_id: UUID | None = None
    reviewed: bool | None = None
```

## OpenAPI codegen → frontend client

Pipeline:
1. `nx run api:openapi` runs the app in "schema-only" mode and writes
   `apps/api/openapi.json`.
2. `nx run api-client:generate` (TS lib) runs `openapi-typescript-codegen`
   to write `libs/ts/api-client/src/generated/`.
3. The frontend imports from `@vd/api-client`.
4. Both targets run as part of `nx affected` whenever API schemas change.

Wrapper around the generated client adds the `EventSource` SSE helper.

## Error envelope

```json
{ "error": { "code": "DETECTION_NOT_FOUND", "message": "…", "details": {…} } }
```

A FastAPI exception handler maps custom `AppError` subclasses to the envelope.
HTTP status codes are conventional (404, 409, 422).

## Concurrency

- Use `SELECT … FOR UPDATE SKIP LOCKED` only in the worker (review queue
  pick), not in the API.
- For label correction PATCH: optimistic concurrency via `updated_at` IF the
  UI starts allowing concurrent editors. v1 single-user → not necessary.

## Testing

- Harness: `vd_db.testing` provisions a throwaway `<db>_test_<label>` database
  (schema from `Base.metadata.create_all` + the builtin-class seed; HNSW
  indexes skipped) against the docker-compose Postgres. Each project's
  `conftest.py` builds it once per session and truncates between tests.
- Integration: `httpx.AsyncClient` against the in-process app with `get_db`
  overridden onto the test database. Celery work is asserted via a recorder
  patched over `send_task`.
- Contract: schemathesis or `dredd` against the generated OpenAPI to ensure
  schemas stay in sync with handlers.

## Open questions

- **Pagination keys**: cursor encoding — use `(created_at, id)` for stable
  ordering. Document; do not surface format to consumers.
- **CORS**: dev server allows `http://localhost:5173`. Single-user so no
  multi-origin concerns.
- **CSRF**: none, no cookies, no auth.

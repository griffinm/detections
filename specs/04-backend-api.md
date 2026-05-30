# 04 — Backend API

## Stack

- **FastAPI** with **`uvicorn`** in dev (gunicorn + uvicorn workers in prod).
- **SQLAlchemy 2.x async** via `asyncpg`.
- **Pydantic v2** models (request/response).
- **Cursor pagination** via the in-tree helper in
  `apps/api/src/api/utils/pagination.py` — see "Pagination" below.
- **SSE** (server-sent events) for live processing progress (simpler than
  WebSockets, and we only need server→client).
- Configuration via `libs/python/settings.Settings`.

The API does NOT enqueue heavy work itself — it writes to the DB and pushes
Celery tasks to Redis. The worker spec (05) covers task semantics.

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
│       │   ├── jobs.py                  # external video submission + result
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
from .routers import (clips, jobs, frames, detections, classes, subclasses,
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
    for r in (clips, jobs, frames, detections, classes, subclasses, labeling,
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

All paths prefixed with `/api`. List endpoints use cursor pagination — see
"Pagination" below for the request shape, response envelope, and shared helper.

### Clips
- `GET /clips?status=&q=` — list, paginated.
- `POST /clips/upload` *(multipart, Phase 8)* — accept a browser video upload
  and write it into `VD_INBOX_DIR`. The file streams to a hidden `.part` file
  and is atomically renamed to its final video name; the ingest-watcher then
  enqueues `vd.ingest_video` exactly like a manual drop. The API creates **no**
  `clips` row and enqueues nothing itself — that would race the watcher into a
  duplicate, metadata-less row (the same reason `intake/` is unwatched; see
  spec 02 §External video submission). Rejects non-video extensions with 415.
  Returns 202 `{filename, size_bytes}`; the clip row arrives over SSE
  (`clip.created`) once the watcher ingests it. Declared before `/{clip_id}`
  so the literal path wins the route match.
- `GET /clips/{id}` — detail, includes frame count + detection count.
- `DELETE /clips/{id}` *(Phase 7)* — enqueues `vd.delete_clip`: cascades frames
  + detections, always removes the frame JPEGs, removes the source video iff
  `delete_processed_videos`. Returns 202; UI updates on the `clip.deleted` SSE.
- `POST /clips/{id}/reprocess` — re-enqueue `detect_frame` for all kept frames
  using the active model.
- `POST /clips/{id}/reextract` — wipe the clip's frames + detections and re-run
  extraction + detection (`vd.reextract_frames`). 409 if the source video is no
  longer on disk; otherwise 202, with the clip's status returning to
  `extracting`. The same SSE event train as a fresh ingest drives the UI.
- `GET /clips/{id}/video` — stream the source video at `clip.final_path` for
  the in-app player. Returns a `FileResponse` so `Accept-Ranges: bytes` and
  HTTP `Range` requests work for `<video>`-element seeking. `Content-Type` is
  set from the file suffix (defaults to `video/mp4`); the bytes are served
  as-is — HEVC clips rely on the browser's hardware decoder, no transcoding.
  404 when the clip has no `final_path` or the file has been purged.
- `GET /clips/{id}/overlay` — flat list of every non-deleted detection on the
  clip, lean shape `{frame_index, bbox, class_id, subclass_id, track_id,
  confidence_class}`. Ordered by `frame_index`, then `created_at`. Distinct
  from `/detections` (gallery shape with image/crop URLs, capped at 2000):
  drops the URLs and exposes `frame_index` + `track_id`, so the player can
  map `video.currentTime` to a frame and keep a stable colour per tracked
  object across seconds. No pagination — one query per modal open.

### Jobs *(external integration — see spec 02 §External video submission)*

The app-to-app surface for the two upstream apps (UniFi Protect motion
archiver, family-video archiver). They run on the same host and share the
`data/` mount, so videos pass **by path reference**, never as HTTP bodies.

- `POST /api/jobs` — submit a video already written under `VD_INTAKE_DIR`.
  Body:
  ```json
  {
    "source": "unifi-protect",
    "external_id": "evt_8842",
    "video_path": "/data/videos/intake/evt_8842.mp4",
    "callback_url": "http://unifi-archiver:9000/hooks/vd",   // optional
    "metadata": { "trigger": "person", "zone": "driveway" }   // optional
  }
  ```
  The handler: (1) `realpath`-validates `video_path` resolves inside
  `VD_INTAKE_DIR` — a `..` escape or a missing file is `422`; (2) if
  `external_id` is given and a clip with `(source, external_id)` already
  exists, returns it unchanged (idempotent re-submit); (3) otherwise inserts a
  `clips` row — `status='pending'`, generated UUIDv7, `source`/`external_id`/
  `callback_url` set, `external_metadata = metadata`; (4) enqueues
  `vd.ingest_video` on the `cpu` queue with the new `clip_id`. Returns
  `202 { "job_id", "status": "pending" }`. It never blocks on processing —
  this honours the "API does no heavy work" rule (even the SHA hash is left to
  the worker; the API path's idempotency key is `(source, external_id)`).
- `GET /api/jobs/{id}` — job status + result. `status` mirrors `clip_status`:
  `pending|extracting|detecting` = in-flight, `done|failed` = terminal. On a
  terminal status the body carries the full result payload (below). Resolves
  through `canonical_clip_id` when the submitted bytes deduped onto an earlier
  clip.

The job **is** the clip — there is no separate `jobs` table, `job_id == clip_id`.
`/api/jobs` is just the external-facing projection of a clip: submit-shaped in,
result-shaped out. The folder watcher and `POST /api/jobs` converge on the same
`vd.ingest_video` pipeline.

**Result payload** — the body of `GET /api/jobs/{id}` when terminal, and the
webhook body posted by `vd.deliver_callback` (spec 05):
```json
{
  "job_id": "...", "clip_id": "...",
  "source": "unifi-protect", "external_id": "evt_8842",
  "status": "done",
  "clip": { "duration_sec": 8.0, "width": 1920, "height": 1080 },
  "detections": [
    { "class": "person", "subclass": "Mallory",
      "confidence_class": 0.93, "confidence_subclass": 0.81,
      "frame_index": 4, "timestamp_sec": 4.0,
      "bbox": {"x":0.1,"y":0.2,"w":0.2,"h":0.5} }
  ],
  "summary": {
    "classes":    [ { "class": "person", "frames": 7 } ],
    "subclasses": [ { "class": "person", "subclass": "Mallory",
                      "frames": 6, "best_confidence": 0.91 } ]
  }
}
```
- `detections` — per-box detail over **live (non-deleted) detections on kept
  frames**; the UniFi archiver consumes this.
- `summary` — the "who/what appeared in this clip" roll-up; the family archiver
  consumes this.
- Computed on-the-fly from `detections`/`frames`, like `/metrics` — there is no
  stored job-result table. It therefore reflects the *current* labels: if a
  human later re-reviews the clip, a subsequent `GET /api/jobs/{id}` changes.
  The webhook payload is the snapshot frozen at `clip.done`.
- On `status='failed'`, `error` is set and `clip`/`detections`/`summary` are
  omitted.

UniFi Protect supplies its *own* object detections in `metadata`; we store them
in `external_metadata` and do **not** ingest them as `detections` rows — mixing
detection sources would pollute the `detection_audits` accuracy ledger. Our
sub-class recognition is the value-add.

No auth (the system's standing posture — single-user LAN). A shared-secret
header on `POST /api/jobs` + `callback_url` is a sensible future hardening if
these apps ever leave the trusted network — out of scope while everything is
same-host LAN.

### Frames
- `GET /clips/{id}/frames?kept=true` — paginated.
- `GET /frames/{id}` — detail incl. detections (soft-deleted ones excluded).
- `DELETE /frames/{id}` — hard-delete a frame: its JPEG, its row, and (via
  `ondelete=CASCADE`) its detections + audit rows. Synchronous, returns 204.
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
- `POST /detections/{id}/predict` — schedules `vd.predict_user_detection`
  (gpu queue) to run YOLO on the frame and IoU-match against this box's
  bbox. Writes `predicted_class_id`/`confidence_class`; auto-assigns
  `class_id` only when it was null (preserving the user's manual choice
  if any). Returns 202 — the result reaches the UI via the
  `frame.updated` SSE event. The labeling UI debounces this call ~1 s
  after the last draw/resize.
- `POST /detections/{id}/promote-example` — promotes to `subclass_examples`. *(Phase 4)*
- `GET /detections/{id}/crop?size=192` — returns a small JPEG of the bbox
  region (Pillow crop + Lanczos resize), with disk caching under
  `<frames_dir>/.thumbs/<detection_id>_<bbox_hash>_<size>.jpg`. The cache key
  includes a hash of the bbox so a resized box yields a different filename
  (old crops become harmless orphans). 410 once the source frame is purged.
  Lets the class-detail gallery render hundreds of tiles without each one
  pulling the full frame JPEG (the original CSS-crop approach loaded
  hundreds of MB into the page).
- Detection mutations publish a `frame.updated` SSE event.

### Classes / Subclasses *(subclass endpoints: Phase 4)*
- `GET /classes`, `POST /classes`, `PATCH /classes/{id}`, `DELETE /classes/{id}`.
  `POST /classes` accepts an optional `yolo_class_index`; supplying it links
  the new class to that YOLO output index so detections of that class are
  routed to the row immediately (no model re-activation needed). The index
  must be unique across `classes` — duplicates are rejected with `409`.
  `DELETE` is a soft delete (`is_active=false`); `PATCH {is_active:true}`
  reactivates. The `/classes` page exposes both directions (Deactivate /
  Reactivate) so a soft-deleted class is recoverable from the UI — the
  labeling picker only lists `is_active` classes, so deactivating hides a
  class from assignment without losing its audited detections.
- `GET /classes/catalog` — names offered to the "New class" picker: the
  union of the active base YOLO model's class list (`kind="yolo"`,
  `target_class_id IS NULL`, `is_active=true`, read from
  `ModelVersion.metrics["class_names"]`) and the COCO-80 baseline. Each
  entry is `{name, yolo_class_index, in_use}`. The active model's index
  wins where both know the name; names only present in COCO-80 (e.g. ones
  a fine-tune has trimmed away) return `yolo_class_index=null` —
  `_sync_yolo_class_index` fills the right value if a model that knows
  the name is later activated. `in_use` flags names already in `classes`.
  Falls back to pure COCO-80 when no YOLO model is active.
- `GET /classes/{id}/subclasses`, `POST /classes/{id}/subclasses` — creating
  the *first* active sub-class enqueues `vd.backfill_embeddings`.
- `POST /classes/{id}/rescan-subclasses` — manually re-enqueue
  `vd.backfill_embeddings` for the class (powers the UI re-scan button).
- `GET /subclasses?class_id=`, `GET /subclasses/{id}`, `PATCH /subclasses/{id}`,
  `DELETE /subclasses/{id}` (soft delete via `is_active`).
- `GET /subclasses/{id}/examples?cursor=&limit=` — `Paginated[SubclassExampleRead]`
  (see "Pagination"). Each item carries the detection bbox, the frame image
  URL, and a `crop_url` pointing at the server-cropped thumbnail endpoint.
- `POST /subclasses/{id}/examples` — add an example; `DELETE …/examples/{id}`.
- `GET /subclasses/{id}/detections?include=&sort=&cursor=&limit=` — every
  non-deleted detection tagged with this sub-class. `include` ∈ `all` (default)
  | `auto` (`reviewed=false`) | `reviewed` (`reviewed=true`). `sort` ∈
  `created_desc` (default) | `reviewed_desc` (`reviewed_at DESC NULLS LAST,
  created_at DESC`). Returns `Paginated[DetectionGalleryItem]` — a lean shape
  (id, frame_id, clip_id, class_id, subclass_id, bbox, image_url, crop_url,
  source, reviewed, reviewed_at, created_at) tuned for the class-detail page
  gallery. The UI renders the `crop_url` thumbnail; `image_url`/`bbox` stay on
  the row for callers that need the full frame. Note: these gallery endpoints
  use offset-based cursors (the cursor is the next offset) rather than the
  keyset cursors documented in "Pagination" — `reviewed_desc`'s NULLS LAST
  ordering doesn't map cleanly to a single `(sort_col, id)` keyset. The
  response envelope is identical so the frontend's `useCursorInfiniteQuery`
  works either way.
- `GET /classes/{id}/detections?include=&sort=&cursor=&limit=` — same shape
  and params, aggregates across every sub-class (or none) of this class.
- `GET /classes/{id}/examples?cursor=&limit=` — `Paginated[SubclassExampleRead]`
  rolled up across the class's active sub-classes (newest first). Powers the
  class-level "Examples" tab; sub-class `color_hex` keys the per-tile border
  in the UI.

### Labeling queue + bulk shortcuts
- `GET /labeling/queue?strategy=&class_id=&limit=` — ordered list of frames
  with unreviewed detections. `strategy` ∈ `lowconf` (lowest unreviewed
  `confidence_class` first) | `unreviewed` (newest frame first). The optional
  `class_id` filters to frames with an unreviewed detection of that class and
  scopes the per-frame counts to it. The kNN `recent corrections` strategy is
  deferred (`specs/deferred.md`). The UI holds the returned ordering for
  keyboard (`J`/`K`) navigation.
- `GET /labeling/predicted-groups?class_id=&min_confidence=` — group
  unreviewed detections by `(class, predicted_subclass, confidence_bucket)`
  where the bucket is `high ≥0.85 / med ≥0.7 / low ≥ min_confidence`.
  `min_confidence` defaults to the effective `subclass_min_confidence`
  setting (the same gate the worker uses), so the surface matches what kNN
  actually committed. Returns `{class_id, class_name, predicted_subclass_id,
  predicted_subclass_name, confidence_bucket, count, sample_detection_ids}`
  ordered by bucket desc, count desc — the bulk page renders each row as a
  card with up to 9 thumb previews.
- `GET /labeling/predicted-group-detections?predicted_subclass_id=&bucket=&limit=`
  — full `DetectionGalleryItem[]` for one (subclass, bucket) cell, ready to
  paint into the bulk tile grid.
- `POST /labeling/bulk-review` — body `{detection_ids:[uuid], class_id?,
  subclass_id?, reviewed?}`. Applies the same set of field changes to many
  detections in one transaction; the audit reason is inferred per row
  exactly like the per-detection PATCH (`user_reassign` when class/subclass
  changes, `user_review` when reviewed flips false→true). Skips
  soft-deleted rows and rows whose `class_id` would clash with the chosen
  `subclass_id` (unless `class_id` is provided to override). Idempotent — a
  no-op re-apply writes zero audits. Returns
  `{updated, skipped, audits_written, affected_frame_ids}`; publishes one
  `frame.updated` SSE per affected frame and best-effort triggers training.

- `POST /labeling/bulk-review-tracks` — body `{track_ids:[uuid], class_id?,
  subclass_id?, reviewed?}`. Same semantics as `bulk-review` but the unit of
  work is a track: each track row updates plus per-detection audits land for
  every member that actually changed. Skips tracks where the chosen sub-class
  belongs to a different class than the track's (unless `class_id` overrides).
  Returns `{updated_tracks, updated_detections, skipped_tracks, audits_written,
  affected_frame_ids, affected_track_ids}`; publishes one `track.updated` per
  changed track and one `frame.updated` per affected frame.

### Tracks *(Phase 9 Stage B)*
- `GET /clips/{clip_id}/tracks` — every live track for a clip ordered by
  `first_frame_index`. Returns `TrackRead[]` (track header — no member detections).
- `GET /tracks/{id}` — `{track: TrackRead, members: TrackMember[]}` ordered
  by `frame_index`.
- `PATCH /tracks/{id}` — body `{class_id?, subclass_id?, reviewed?}`. Applies
  the change to the track row, writes the matching `TrackAudit` rows
  (`user_reassign` and/or `user_review`), and fans out to every live member
  detection: per-detection `user_reassign` / `user_review` audits land in
  `detection_audits` exactly as if the user had clicked each box. Returns
  `{track, updated_detections, audits_written, affected_frame_ids}`.
- `POST /tracks/{id}/split` — body `{pivot_frame_index: int}`. Carves
  detections with `frame_index >= pivot` off into a new `source='user'`
  track (copying class/subclass from the original). Rejects with 422 if the
  pivot would leave either half empty. Writes a `TrackAudit(reason='user_split',
  from_track_id=original.id, pivot_frame_index, n_detections_moved)` on the
  **new** track. Publishes `track.split`. Returns the new track's full detail.
- `POST /tracks/{id}/merge` — body `{other_track_id: uuid}`. Reassigns every
  detection of `other` to this track, soft-deletes `other`, and writes a
  `TrackAudit(reason='user_merge', from_track_id=other.id, n_detections_moved)`.
  Rejects with 422 if the two tracks belong to different clips, different
  classes, or their frame ranges overlap. Publishes `track.merged`.
- `DELETE /tracks/{id}` — soft-delete the track. Cascade soft-deletes every
  live member detection (with `DetectionAudit(reason='user_delete')` per
  member) plus a `TrackAudit(reason='user_delete')`. Publishes `track.deleted`.

### Clip-scoped detections
- `GET /clips/{id}/detections?class_id=&subclass_id=&include=&limit=` — every
  non-deleted detection in this clip, ordered by `frame_index` then
  `created_at` so a clip reads left-to-right. Returns the
  `DetectionGalleryItem[]` shape. Powers the "bulk-label this clip" tile
  grid, where the user multi-selects and applies a sub-class via
  `POST /labeling/bulk-review`.
- `GET /clips/{id}/class-summary` — `[{class_id, class_name, count}]`
  ordered most-common-first, so the bulk-label page can default the class
  filter to the dominant subject in the clip.

### Models + training
- `GET /models?kind=&is_active=&cursor=&limit=` — list versions,
  cursor-paginated (`Paginated[ModelVersionRead]`). `kind` filters on the
  `model_kind` enum (`yolo` / `insightface` / `classifier`); `is_active`
  is a bool.
- `POST /models/{id}/activate` — switch active weights.
- `POST /training-runs` — body: `{ kind, target_class_id? }` — enqueues a job.
- `GET /training-runs?status=&kind=&cursor=&limit=` — list, cursor-paginated
  (`Paginated[TrainingRunRead]`). `status` accepts the bucket form
  (`running` / `done` / `failed` / `queued`) that the frontend stat strip
  emits — bucket-to-enum mapping lives in the router next to the route.
- `GET /training-runs/counts?kind=` — `{ all, running, done, failed, queued }`.
  Respects `kind`, ignores `status` — the stat strip needs to show what each
  bucket *would* contain under the current kind, independent of the active
  status filter. (This is the canonical shape for any future faceted-counts
  endpoint; see "Pagination" below.)
- `GET /training-runs/{id}` — incl. tail of log + metrics.
- `POST /training-runs/{id}/cancel` — flips a `queued`/`running` row to
  `cancelled`, publishes `training_run.update`. Best-effort: a genuinely
  in-flight task won't observe the cancel mid-training and may still
  overwrite the row on completion — the endpoint exists to clear runs
  orphaned by a worker crash (worker also sweeps these on boot, see spec 05).
  Returns 409 if the run already terminated.

### Metrics *(Phase 6 — computed on-the-fly, no materialized view)*
- `GET /metrics/accuracy?bucket=day|week&from=&to=&class_id=&model_version_id=`
  — class/sub-class top-1 time series, grouped by `(period, model_version)`.
- `GET /metrics/per-class?model_version_id=` — per-class precision & recall.
- `GET /metrics/calibration?class_id=&model_version_id=` — confidence-decile
  buckets → empirical accuracy, plus ECE.
- `GET /metrics/summary` — dashboard tiles (counts, last 7d accuracy).
- `GET /metrics/changes?limit=` — recent class/sub-class reassignments (the
  "what changed" panel) from `detection_audits`.
- `GET /metrics/tracks?bucket=day|week&from=&to=&class_id=&model_version_id=`
  — track-level top-1 accuracy time series. A track "counts" once it has
  `reviewed=true`; the model's prediction is `tracks.predicted_class_id` /
  `predicted_subclass_id` versus the current (user-confirmed) values.
  Filtered to `source='tracker'` (user-created tracks via split have no
  model prediction to score).

### Settings *(Phase 7 — implemented)*
- `GET /settings` — list overridable tunables: effective value, env default, type.
- `PUT /settings/{key}` — validate + upsert a `settings_kv` override.
- `DELETE /settings/{key}` — clear the override (reset to the env default).
- Overrides overlay env defaults via `vd_db.load_effective_settings`, which
  worker/API jobs call per task — edits take effect with no restart. Only the
  `vd_settings.OVERRIDABLE_KEYS` tunables are editable; paths/URLs stay env-only.

- `GET /system/backfill-tracks` — count of pre-Phase-9 clips (have
  detections, no live track). Phase 9 Stage B; surfaced on `/system`.
- `POST /system/backfill-tracks` — body `{limit}` — enqueue
  `vd.backfill_tracks(limit)` to sweep that many clips into the tracking
  pipeline.
- `POST /clips/{clip_id}/backfill-tracks` — targeted variant; enqueues
  `vd.backfill_tracks(clip_id, 1)` for one clip. Idempotent (the worker
  skips clips that already have a live track).

### System *(Phase 7 — `disk`/`purge-frames` implemented)*
- `GET /system/health` — DB+Redis+models reachable?
- `GET /system/queue` — celery queue depths via `inspect`. *Deferred* — Flower
  (`:5555`) already covers queue inspection (`specs/deferred.md`).
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

## Pagination

The canonical contract for list endpoints. Helper:
`apps/api/src/api/utils/pagination.py` — the source of truth, do not duplicate
the encoding logic in routes.

**Request.** `?cursor=<opaque>&limit=<int>` plus the resource's own filters.
`limit` defaults to 50 and is clamped to `[1, 200]`. Routes consume the
`cursor_params` dependency to get a parsed `(cursor, limit)`.

**Response envelope** — `Paginated[T]` from
`apps/api/src/api/schemas/common.py`:
```json
{ "items": [...], "total": 739, "next_cursor": "eyJ2Ijoi..." }
```
`total` is the **filtered** count (matches what's being scrolled). `next_cursor`
is `null` on the last page.

**Cursor.** Opaque to consumers — current format is base64-url JSON over
`(sort_value, id)`, but **do not document the bytes**; the helper may change
without notice. Decoding is permissive: a cursor whose anchor row has since
been deleted is still a valid keyset anchor (keyset paging slices "rows
strictly older than the encoded value, id" — deletion doesn't break that).
Only malformed cursors return `400`.

**Ordering.** Always `(sort_col, id) DESC` (descending), where `sort_col` is
typically `created_at`. The id is the stable tiebreaker — under UUID v7 PKs
the id is itself time-sorted, so the composite key is monotonic.

**Indexing.** Each paginated resource needs a composite
`(sort_col DESC, id DESC)` btree to keep the keyset query plan an index-only
scan — e.g. `ix_training_runs_created_at_id_desc`.

**Faceted counts** (e.g. status buckets in a stat strip): expose at
`<resource>/counts?<orthogonal_filters>` returning a small dict. Counts
respect the orthogonal filters (e.g. `kind`) but **never** the facet itself
(e.g. `status`) — the strip's job is to let the user pivot between buckets,
so each bucket count must show what it would contain. Don't inline counts in
the list envelope: filter and facet have different lifetimes and the
dedicated endpoint is independently cacheable.

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

- **CORS**: dev server allows `http://localhost:5173`. Single-user so no
  multi-origin concerns.
- **CSRF**: none, no cookies, no auth.

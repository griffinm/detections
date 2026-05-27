# 03 — Data Model

## Conventions

- All tables use `bigserial` (or UUID v7) PKs. Recommendation: **UUID v7** —
  monotonically sortable, no enum-leak risk in URLs. Stored as `uuid` column.
- `created_at` / `updated_at` `timestamptz NOT NULL DEFAULT now()` on every
  table. `updated_at` maintained by a trigger (or by the ORM `onupdate`).
- Soft delete where an audit trail must be preserved: `classes` /
  `subclasses` (deactivated via `is_active`) and `detections` (`deleted_at`).
  A detection is soft-deleted because `detection_audits.detection_id` is
  `ON DELETE CASCADE` — a hard delete would erase its `user_delete` row.
  Everything else is hard-delete.
- All FKs are `ON DELETE` explicit (CASCADE, SET NULL, or RESTRICT — called
  out per relationship).
- `pgvector` enabled in init.sql (`CREATE EXTENSION IF NOT EXISTS vector;`).

## Tables

### `clips`

The original ingested video.

| Column           | Type            | Notes                                                  |
|------------------|-----------------|--------------------------------------------------------|
| id               | uuid PK         |                                                        |
| filename         | text NOT NULL   | basename at ingest                                     |
| original_path    | text NOT NULL   | absolute path inside `inbox/` at ingest                |
| final_path       | text            | where the file ended up (`processed/`)                 |
| sha256           | text NOT NULL UNIQUE | content hash; ingest dedup                        |
| size_bytes       | bigint NOT NULL | overwritten by `vd.compress_video` with the post-HEVC size |
| duration_sec     | numeric(10,3)   | from ffprobe                                           |
| fps              | numeric(6,3)    | source fps                                             |
| width            | int             |                                                        |
| height           | int             |                                                        |
| codec            | text            | initial value from ffprobe; `vd.compress_video` flips it to `'hevc'` after a successful transcode (spec 05) |
| status           | clip_status NOT NULL DEFAULT 'pending' | enum (see below)                |
| error            | text            | if status='failed'                                     |
| ingested_at      | timestamptz     |                                                        |
| processed_at     | timestamptz     |                                                        |
| source           | text NOT NULL DEFAULT 'watch' | origin label: `watch` (folder watcher), `unifi-protect`, `family-archive`, … |
| external_id      | text            | the submitting app's own record id, for correlation    |
| callback_url     | text            | webhook target for the job result; NULL → poll-only    |
| external_metadata| jsonb           | submitter-supplied metadata (e.g. UniFi's own detections) — stored, not interpreted |
| canonical_clip_id| uuid REFERENCES clips(id) ON DELETE SET NULL | set iff this clip's bytes duplicate an earlier clip; job results resolve through it |

```sql
CREATE TYPE clip_status AS ENUM
  ('pending','extracting','detecting','done','failed');
```

Indexes: `(status)`, `(ingested_at DESC)`,
`(source, external_id) WHERE external_id IS NOT NULL`.

The last five columns support **external job submission** (spec 04 §Jobs). A
folder-watcher drop leaves them at their defaults (`source='watch'`, the rest
NULL). `POST /api/jobs` is idempotent on `(source, external_id)` — a re-submit
returns the existing clip rather than creating a duplicate. `source` is free
text, not an enum, so a new integration needs no migration. `canonical_clip_id`
handles the rarer case of *identical bytes* arriving as a fresh job: SHA dedup
in `vd.ingest_video` sets it to the earlier clip, marks this row `done`, and
the job result + callback serve the canonical clip's detections.

### `frames`

One row per extracted JPEG. A frame is set `kept=false` only when it is a
near-duplicate of an adjacent frame collapsed by `vd.dedup_clip_frames` (spec
05); its JPEG is then unlinked. Frames with no detections above
`detection_min_confidence` stay `kept=true` and on disk — YOLO can miss
objects, and the labeling UI lets the user add a box manually after the fact.

| Column        | Type         | Notes                                                |
|---------------|--------------|------------------------------------------------------|
| id            | uuid PK      |                                                      |
| clip_id       | uuid NOT NULL REFERENCES clips(id) ON DELETE CASCADE |                |
| frame_index   | int NOT NULL | sequential within clip (1-based)                     |
| timestamp_sec | numeric(10,3) NOT NULL | offset into the source clip                |
| path          | text         | NULL once pruned                                     |
| width         | int NOT NULL |                                                      |
| height        | int NOT NULL |                                                      |
| phash         | bytea        | 64-bit perceptual hash; near-dup pruning (`vd.dedup_clip_frames`, spec 05). NULL on pre-feature frames until `vd.backfill_frame_phash` runs |
| kept          | bool NOT NULL DEFAULT true | false → near-duplicate collapsed by `vd.dedup_clip_frames`; its JPEG is then unlinked |
| detect_status | detect_status NOT NULL DEFAULT 'pending'  | enum                    |

```sql
CREATE TYPE detect_status AS ENUM ('pending','done','failed');
```

Indexes: `(clip_id, frame_index)` UNIQUE, `(detect_status)`, `(kept) WHERE kept`.

### `classes`

| Column      | Type        | Notes                                              |
|-------------|-------------|----------------------------------------------------|
| id          | uuid PK     |                                                    |
| name        | text NOT NULL UNIQUE | display name, e.g. "person", "deer"       |
| source      | class_source NOT NULL | enum: 'builtin','custom'                  |
| yolo_class_index | int    | the active YOLO model's class index for this class; nullable for classes not yet present in the model |
| color_hex   | text NOT NULL DEFAULT '#888888'  |                                |
| is_active   | bool NOT NULL DEFAULT true |                                         |

```sql
CREATE TYPE class_source AS ENUM ('builtin','custom');
```

Seeded `builtin` rows: `person`, `car`, `dog`, `bear`. (We don't add `deer`
or `face` here — `deer` is custom; face recognition is handled within
`person`.) Migration `002` populates their `yolo_class_index` with the COCO
indices (`person=0, car=2, dog=16, bear=21`) so the detector can map a YOLO
class index back to a `classes` row. Detections of other COCO classes are
dropped.

### `subclasses`

| Column      | Type    | Notes                                                  |
|-------------|---------|--------------------------------------------------------|
| id          | uuid PK |                                                        |
| class_id    | uuid NOT NULL REFERENCES classes(id) ON DELETE CASCADE |          |
| name        | text NOT NULL |                                                  |
| color_hex   | text NOT NULL DEFAULT '#888888' |                                |
| is_active   | bool NOT NULL DEFAULT true |                                     |
| (class_id, name) UNIQUE | | |

### `detections`

The core table. One row per bounding box on a frame. Stores both the
**predicted** state at the time of inference and the **current** state
(possibly user-corrected).

| Column                | Type               | Notes                                       |
|-----------------------|--------------------|---------------------------------------------|
| id                    | uuid PK            |                                             |
| frame_id              | uuid NOT NULL REFERENCES frames(id) ON DELETE CASCADE |        |
| class_id              | uuid REFERENCES classes(id) ON DELETE SET NULL | current (possibly user-set) |
| subclass_id           | uuid REFERENCES subclasses(id) ON DELETE SET NULL | current      |
| bbox                  | jsonb NOT NULL     | `{x,y,w,h}` normalized 0..1                 |
| confidence_class      | real               | only for source='model'                     |
| confidence_subclass   | real               |                                             |
| source                | det_source NOT NULL | enum: 'model','user'                       |
| model_version_id      | uuid REFERENCES model_versions(id) ON DELETE SET NULL | which detector produced it |
| predicted_class_id    | uuid REFERENCES classes(id) ON DELETE SET NULL | what the model said   |
| predicted_subclass_id | uuid REFERENCES subclasses(id) ON DELETE SET NULL |                    |
| reviewed              | bool NOT NULL DEFAULT false | user has confirmed/corrected       |
| reviewed_at           | timestamptz        |                                             |
| deleted_at            | timestamptz        | soft delete; NULL = live, set = user-removed (migration 003) |
| face_embedding        | vector(512)        | InsightFace ArcFace; NULL for non-face      |
| object_embedding      | vector(768)        | DINOv2-S; NULL until computed               |
| track_id              | uuid REFERENCES tracks(id) ON DELETE SET NULL | NULL when tracker didn't link, or for pre-Phase-9 detections |

```sql
CREATE TYPE det_source AS ENUM ('model','user');
```

Indexes:
- `(frame_id)`
- `(class_id, reviewed)` for accuracy queries
- HNSW on `face_embedding` (`vector_cosine_ops`)
- HNSW on `object_embedding` (`vector_cosine_ops`)
- `(track_id) WHERE track_id IS NOT NULL` for track membership lookups

Why keep `predicted_class_id` alongside `class_id`?
The requirement is to track accuracy of automatic assignments over time. We
need to know what the *model said* and what the *truth turned out to be*.
Storing both on the same row keeps it simple — the audit log (below) records
the *transitions*, but the current+original snapshot lives here.

### `tracks`

A sequence of detections believed to be the same physical object within one
clip. Populated by `vd.detect_and_track_clip` (BoT-SORT). Sub-class
assignment runs at the track level — `vd.assign_track_subclass` votes across
member detections, which is more robust at 1 fps than per-frame kNN.

| Column                | Type            | Notes                                                       |
|-----------------------|-----------------|-------------------------------------------------------------|
| id                    | uuid PK         |                                                             |
| clip_id               | uuid NOT NULL REFERENCES clips(id) ON DELETE CASCADE |                |
| class_id              | uuid REFERENCES classes(id) ON DELETE SET NULL | current (majority/user)         |
| subclass_id           | uuid REFERENCES subclasses(id) ON DELETE SET NULL | current (vote/user)         |
| predicted_class_id    | uuid REFERENCES classes(id) ON DELETE SET NULL | tracker's class vote            |
| predicted_subclass_id | uuid REFERENCES subclasses(id) ON DELETE SET NULL | recognition vote             |
| confidence_class      | real            | mean over the track's detection scores                      |
| confidence_subclass   | real            | mean similarity of the winning sub-class vote               |
| n_detections          | int NOT NULL DEFAULT 0 |                                                      |
| first_frame_index     | int NOT NULL    | min `frame_index` over live members                         |
| last_frame_index      | int NOT NULL    | max `frame_index` over live members                         |
| source                | track_source NOT NULL | enum: 'tracker','user' ('user' reserved for Stage B split/merge) |
| model_version_id      | uuid REFERENCES model_versions(id) ON DELETE SET NULL | YOLO version that produced it |
| reviewed              | bool NOT NULL DEFAULT false |                                                 |
| reviewed_at           | timestamptz     |                                                             |
| deleted_at            | timestamptz     | soft delete; parallels `detections.deleted_at`              |

```sql
CREATE TYPE track_source AS ENUM ('tracker','user');
```

Indexes: `(clip_id, first_frame_index)`, `(class_id, reviewed)`,
`(clip_id) WHERE deleted_at IS NULL`.

`detections.track_id` is a nullable FK to `tracks(id)` ON DELETE SET NULL.
Pre-Phase-9 detections stay NULL; a tracker-dropped single-frame detection
also stays NULL.

### `subclass_examples`

User-curated canonical examples used as the kNN reference set for sub-class
assignment. A subset of `detections`.

| Column        | Type    | Notes                                                |
|---------------|---------|------------------------------------------------------|
| id            | uuid PK |                                                      |
| subclass_id   | uuid NOT NULL REFERENCES subclasses(id) ON DELETE CASCADE |    |
| detection_id  | uuid NOT NULL REFERENCES detections(id) ON DELETE CASCADE |    |
| starred       | bool NOT NULL DEFAULT true |                                     |
| (subclass_id, detection_id) UNIQUE | | |

Lookup pattern: when assigning a sub-class to a new detection, kNN over the
embeddings of `subclass_examples` for that class_id.

### `model_versions`

| Column         | Type     | Notes                                                |
|----------------|----------|------------------------------------------------------|
| id             | uuid PK  |                                                      |
| kind           | model_kind NOT NULL | enum: 'yolo','insightface','classifier'   |
| name           | text NOT NULL | e.g. 'yolo11l-finetune-2025-01-12'              |
| weights_path   | text NOT NULL |                                                 |
| target_class_id| uuid     | non-null for classifier kind                         |
| trained_on     | int      | label count at train time                            |
| metrics        | jsonb    | mAP, val accuracy, etc.                              |
| is_active      | bool NOT NULL DEFAULT false |                                   |

```sql
CREATE TYPE model_kind AS ENUM ('yolo','insightface','classifier');
```

Constraints: only one row per `kind`/`target_class_id` may have `is_active=true`.

### `training_runs`

| Column          | Type    | Notes                                              |
|-----------------|---------|----------------------------------------------------|
| id              | uuid PK |                                                    |
| kind            | model_kind NOT NULL |                                        |
| target_class_id | uuid    |                                                    |
| status          | run_status NOT NULL DEFAULT 'queued' | enum               |
| started_at      | timestamptz |                                                |
| finished_at     | timestamptz |                                                |
| metrics         | jsonb   |                                                    |
| log_path        | text    | location of training log                           |
| error           | text    |                                                    |

```sql
CREATE TYPE run_status AS ENUM ('queued','running','succeeded','failed','cancelled');
```

### `detection_audits`

The accuracy ledger. One row per transition (model prediction → user state,
or user state → user state).

| Column         | Type    | Notes                                              |
|----------------|---------|----------------------------------------------------|
| id             | bigserial PK |                                               |
| detection_id   | uuid NOT NULL REFERENCES detections(id) ON DELETE CASCADE | |
| at             | timestamptz NOT NULL DEFAULT now() |                          |
| from_class_id  | uuid    |                                                    |
| to_class_id    | uuid    |                                                    |
| from_subclass_id | uuid  |                                                    |
| to_subclass_id | uuid    |                                                    |
| reason         | audit_reason NOT NULL | enum                                 |
| model_version_id | uuid  | which model version is being judged                |

```sql
CREATE TYPE audit_reason AS ENUM
  ('initial_prediction','user_review','user_reassign','user_delete','retrain_reassign');
```

This is what we slice for accuracy-over-time charts. Insert-only.

### `track_audits`

The track-shape ledger. Track-level events — split, merge, reassign, review,
delete — write rows here. Per-detection class/subclass propagation from a
track-level PATCH still flows through `detection_audits` with the existing
`user_reassign` / `user_review` reasons; the `audit_reason` enum is
intentionally not extended.

| Column             | Type    | Notes                                              |
|--------------------|---------|----------------------------------------------------|
| id                 | bigserial PK |                                               |
| track_id           | uuid NOT NULL REFERENCES tracks(id) ON DELETE CASCADE | |
| at                 | timestamptz NOT NULL DEFAULT now() |                       |
| reason             | track_audit_reason NOT NULL | enum                          |
| from_class_id      | uuid REFERENCES classes(id) ON DELETE SET NULL | for `user_reassign` |
| to_class_id        | uuid REFERENCES classes(id) ON DELETE SET NULL |                  |
| from_subclass_id   | uuid REFERENCES subclasses(id) ON DELETE SET NULL |               |
| to_subclass_id     | uuid REFERENCES subclasses(id) ON DELETE SET NULL |               |
| from_track_id      | uuid | the other track in a split/merge; no FK because the original may have been soft-deleted |
| to_track_id        | uuid |                                                              |
| pivot_frame_index  | int  | non-null for `user_split`                                    |
| n_detections_moved | int  | how many detections moved in a split/merge                   |
| model_version_id   | uuid REFERENCES model_versions(id) ON DELETE SET NULL |          |

```sql
CREATE TYPE track_audit_reason AS ENUM
  ('initial','user_reassign','user_review','user_split','user_merge','user_delete');
```

`initial` is emitted by `vd.detect_and_track_clip` when a new track row is
created, so the ledger has a "first seen at" row per track without scanning
detections. Indexes: `(track_id, at DESC)`, `(reason)`.

### `daily_metrics` (materialized view; refreshed nightly + on demand)

Pre-aggregated metrics, broken out per class, per model_version, per day:
- detections produced
- detections reviewed
- top-1 class accuracy (`predicted_class_id == class_id` among reviewed)
- per-class precision / recall against reviewed set
- sub-class top-1 accuracy
- mean confidence at correctness buckets (for calibration)

Schema details are in spec 06.

### `settings_kv`

Small admin-tweakable settings live in the DB so they can change without an
app restart:

| key (text PK) | value (jsonb) |
|---------------|---------------|

Examples: `frame_fps`, `detection_min_confidence`,
`subclass_retrain_threshold`. These shadow the values in `.env`; the
DB takes precedence if present. Surfaced via the `/settings` API.

### `webhook_deliveries`

The outbound-callback ledger for external jobs. One row per `(clip, event)`
delivery attempt-set — created when a clip with a `callback_url` reaches a
terminal status, worked by `vd.deliver_callback` (spec 05). Persisting it
means a delivery survives a worker restart and is inspectable when a submitter
claims it never heard back.

| Column          | Type     | Notes                                                 |
|-----------------|----------|-------------------------------------------------------|
| id              | uuid PK  |                                                       |
| clip_id         | uuid NOT NULL REFERENCES clips(id) ON DELETE CASCADE | |
| url             | text NOT NULL | snapshot of `clips.callback_url` at enqueue time |
| event           | text NOT NULL | `clip.done` or `clip.failed`                     |
| status          | delivery_status NOT NULL DEFAULT 'pending' | enum               |
| attempts        | int NOT NULL DEFAULT 0  |                                       |
| last_attempt_at | timestamptz |                                                   |
| response_status | int      | HTTP status of the most recent attempt               |
| last_error      | text     | transport error / non-2xx body of the last attempt   |
| payload         | jsonb NOT NULL | the result body sent (spec 04 §Jobs result shape) |
| created_at      | timestamptz NOT NULL DEFAULT now() |                         |
| updated_at      | timestamptz NOT NULL DEFAULT now() |                         |

```sql
CREATE TYPE delivery_status AS ENUM ('pending','delivered','failed');
```

Indexes: `(clip_id)`, `(status) WHERE status = 'pending'` (the retry sweep).
`status='failed'` is terminal — set once `attempts` reaches
`VD_WEBHOOK_MAX_ATTEMPTS`.

## Migrations (Alembic)

- Located in `libs/python/db/alembic/`.
- `alembic.ini` configured to read connection string from `Settings`.
- `nx run db:migrate` is the canonical "apply migrations" target.
- Initial migration creates the extension, enums, all tables, indexes
  (including HNSW vector indexes), and seeds builtin classes.
- Vector index creation order: create table → fill with data → create HNSW
  index. The initial migration can create the empty index immediately
  (HNSW handles incremental inserts fine).

## ER diagram (text)

```
clips ─┬───< frames ─┬───< detections >─── classes
       │             │         │
       │             │         └─── subclasses (>── classes)
       │             │         │
       │             │         ├─── subclass_examples
       │             │         │
       │             │         └─── track_id ──> tracks
       │             │
       │             └─── (file on disk)
       │
       ├───< tracks (per-clip; aggregates detections; see spec 05)
       ├───< webhook_deliveries   (external-job callbacks)
       ├─── canonical_clip_id ──> clips   (self-FK, dedup)
       │
       └─── status, sha256 unique

model_versions ───< training_runs
                ▲
                │
              detections (model_version_id)

detection_audits ──> detections, classes, subclasses, model_versions
track_audits     ──> tracks, classes, subclasses, model_versions
```

## Open questions

- **UUIDv7 in pgvector indexes**: works fine, no special handling needed.
- **`bbox` as jsonb vs separate columns**: jsonb wins on flexibility (we'll
  occasionally want to attach attributes like `occluded`, `truncated` later)
  and the cost is negligible for the scale here. Keep it jsonb but enforce
  the shape with a `CHECK` constraint:
  ```sql
  ALTER TABLE detections
    ADD CONSTRAINT bbox_shape CHECK (
      bbox ? 'x' AND bbox ? 'y' AND bbox ? 'w' AND bbox ? 'h'
    );
  ```
- **Per-class classifier as `joblib` on disk** vs in DB: keep on disk (path
  in `model_versions.weights_path`). Same pattern as YOLO weights.

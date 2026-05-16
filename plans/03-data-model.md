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
| size_bytes       | bigint NOT NULL |                                                        |
| duration_sec     | numeric(10,3)   | from ffprobe                                           |
| fps              | numeric(6,3)    | source fps                                             |
| width            | int             |                                                        |
| height           | int             |                                                        |
| codec            | text            |                                                        |
| status           | clip_status NOT NULL DEFAULT 'pending' | enum (see below)                |
| error            | text            | if status='failed'                                     |
| ingested_at      | timestamptz     |                                                        |
| processed_at     | timestamptz     |                                                        |

```sql
CREATE TYPE clip_status AS ENUM
  ('pending','extracting','detecting','done','failed');
```

Indexes: `(status)`, `(ingested_at DESC)`.

### `frames`

One row per extracted JPEG. Frames whose detections all fall below
`detection_min_confidence` get `kept=false` and the file on disk is removed
(per the requirement).

| Column        | Type         | Notes                                                |
|---------------|--------------|------------------------------------------------------|
| id            | uuid PK      |                                                      |
| clip_id       | uuid NOT NULL REFERENCES clips(id) ON DELETE CASCADE |                |
| frame_index   | int NOT NULL | sequential within clip (1-based)                     |
| timestamp_sec | numeric(10,3) NOT NULL | offset into the source clip                |
| path          | text         | NULL once pruned                                     |
| width         | int NOT NULL |                                                      |
| height        | int NOT NULL |                                                      |
| phash         | bytea        | optional perceptual hash for future dedup            |
| kept          | bool NOT NULL DEFAULT true | false → file deleted from disk         |
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

```sql
CREATE TYPE det_source AS ENUM ('model','user');
```

Indexes:
- `(frame_id)`
- `(class_id, reviewed)` for accuracy queries
- HNSW on `face_embedding` (`vector_cosine_ops`)
- HNSW on `object_embedding` (`vector_cosine_ops`)

Why keep `predicted_class_id` alongside `class_id`?
The requirement is to track accuracy of automatic assignments over time. We
need to know what the *model said* and what the *truth turned out to be*.
Storing both on the same row keeps it simple — the audit log (below) records
the *transitions*, but the current+original snapshot lives here.

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

### `daily_metrics` (materialized view; refreshed nightly + on demand)

Pre-aggregated metrics, broken out per class, per model_version, per day:
- detections produced
- detections reviewed
- top-1 class accuracy (`predicted_class_id == class_id` among reviewed)
- per-class precision / recall against reviewed set
- sub-class top-1 accuracy
- mean confidence at correctness buckets (for calibration)

Schema details are in plan 06.

### `settings_kv`

Small admin-tweakable settings live in the DB so they can change without an
app restart:

| key (text PK) | value (jsonb) |
|---------------|---------------|

Examples: `frame_fps`, `detection_min_confidence`,
`custom_class_finetune_threshold`. These shadow the values in `.env`; the
DB takes precedence if present. Surfaced via the `/settings` API.

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
       │             │         └─── subclass_examples
       │             │
       │             └─── (file on disk)
       │
       └─── status, sha256 unique

model_versions ───< training_runs
                ▲
                │
              detections (model_version_id)

detection_audits ──> detections, classes, subclasses, model_versions
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

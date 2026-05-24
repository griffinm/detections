# 09 — Milestones

This sequences the work in earlier specs into shippable slices. Each phase
ends with something demonstrably working end-to-end, not just scaffolding.

Estimates are rough relative units, not calendar time.

## Phase 0 — Foundations (S)

Goal: empty repo → something that boots.

- NX workspace; `@nxlv/python` with UV; `apps/web` (Vite + React + shadcn
  scaffolded); `apps/api`, `apps/worker`, `apps/ingest-watcher` stubs;
  `libs/python/{db,ml,settings,tasks}` stubs; `libs/ts/{api-client,ui,theme}` stubs.
- `docker-compose.yml` brings up Postgres (with `pgvector`) and Redis.
- Alembic initial migration creates all tables (spec 03), seeds builtin classes.
- Bootstrap script verifies tools, runs `uv sync`, applies migrations.
- Pre-commit + ruff + mypy + eslint + prettier configured.
- API has `/api/system/health` returning DB + Redis OK.
- Web has a dashboard placeholder + theme toggle (light/dark works).
- README documents prerequisites and the bootstrap script.

**Done when:** clone → bootstrap → `nx run-many -t serve` → browser shows
dashboard and `/system/health` returns 200.

## Phase 1 — Ingest + extract (M)

Goal: drop a video, see frames in the UI.

- Folder watcher running (host or container) → enqueues
  `vd.ingest_video` on the `cpu` queue.
- `vd.ingest_video` ffprobes, inserts `clips` row, schedules
  `vd.extract_frames`.
- `vd.extract_frames` runs ffmpeg, inserts `frames` rows.
- Worker (cpu) Docker image builds and runs in compose.
- API routes: `GET /clips`, `GET /clips/:id`, `GET /clips/:id/frames`,
  `GET /files/frames/*` (static mount).
- Web routes: `/clips`, `/clips/:id` — list + frame grid (thumbnails).
- SSE: `clip.status` events update the clips list live.

**Done when:** drop a 30-second mp4 into `inbox/` and within seconds the
clip appears in the UI with ~30 frame thumbnails.

## Phase 2 — Detection (M)

Goal: COCO classes auto-detected on every frame.

- GPU worker Dockerfile + image (CUDA + ultralytics).
- `vd.detect_frame_batch` runs YOLOv11-L on batches; inserts `detections`
  rows; writes initial `detection_audits`.
- Frames with no detections stay on disk so the user can add a missing box
  manually from the labeling UI. (`kept=false` is reserved for dedup'd
  near-duplicates in spec 05.)
- API routes: `GET /frames/:id` includes detections.
- Web: frame detail page draws bboxes over the frame; per-detection
  class label + confidence pill.
- A `nx run worker:gpu-check` target works.

**Done when:** drop a clip with people, cars, and dogs → frames show
correctly drawn bboxes with COCO labels and confidences.

## Phase 3 — Labeling UI (L)

Goal: user can review and correct detections.

- `react-konva` integrated; canvas with image + bbox layer.
- Select / resize / move / delete bboxes.
- Class picker + hotkeys (`1`–`9`) for top-level classes (no sub-class
  selection yet — class picker only).
- Draw-new mode (`B` + drag).
- Eager-save PATCH on each change; SSE invalidates listings.
- Review queue endpoint + page (`/labeling`), strategy=`lowconf`.
- Keyboard nav `J`/`K` advances within the queue.
- Undo/redo, save = mark reviewed.
- Class management UI: `/classes` (CRUD).

**Done when:** user can open `/labeling`, accept the model's good
predictions and correct the bad ones, click "End", and the
`detection_audits` ledger reflects every action.

## Phase 4 — Sub-class assignment (M) — ✅ implemented

Goal: faces are auto-recognized as specific people; sub-classes for other
classes are auto-assigned by embedding kNN.

- InsightFace integrated; `vd.recognize_face` populates `face_embedding`
  on person detections.
- DINOv2-S integrated; `vd.embed_object` populates `object_embedding` on
  non-person detections when their class has any sub-class.
- `vd.assign_subclass` runs kNN against `subclass_examples`.
- Sub-class CRUD + examples gallery UI (`/classes/:id`).
- Labeling UI: sub-class picker (Shift+1…9), "promote to example"
  hotkey (`S`).
- pgvector HNSW index in place; sub-class query latency < 50ms with a
  few thousand examples.

**Done when:** label 5 faces as "Mallory", drop a new clip with Mallory
in it, and the labeling UI shows the model's pre-filled "Mallory" guess
with a confidence > threshold.

## Phase 5 — Custom classes + YOLO fine-tune (L) — ✅ implemented

Goal: user can add a class like "deer" by labeling N frames, and the
detector starts producing deer boxes automatically.

- Class creation flow with `source='custom'`.
- Drawing new boxes for a custom class works (Phase 3 already enables
  this; here we verify the labeling-only flow when no detections exist).
- `vd.finetune_yolo`:
  - Builds dataset from reviewed labels.
  - Trains via ultralytics.
  - Registers + activates new `model_versions` row.
  - Regression guard: mAP delta check before activating.
- Models page (`/models`): list versions, activate/deactivate, see metrics.
- Training page (`/training`): start run, follow progress (SSE), see logs.
- Per-class subclass classifier (`vd.train_subclass_classifier`):
  same lifecycle, smaller scope.
- Optional backfill of recent clips against the new model — *deferred*; new
  clips use the new model automatically, re-detecting old clips is a later add.

**Done when:** label ≥ 100 deer frames, click "Start training", wait, see
new model activate, drop a clip with deer, and deer boxes appear.

## Phase 6 — Accuracy & observability (M) — ✅ implemented

Goal: surface how well the model is doing over time.

- `GET /api/metrics/accuracy|per-class|calibration|summary|changes` — computed
  on-the-fly. The `daily_metrics` materialized view + nightly refresh is
  *deferred* (`specs/deferred.md`); spec 06 frames it as a large-dataset step.
- Metrics page (`/metrics`):
  - Line chart of top-1 class accuracy per day, per model version.
  - Per-class precision/recall table.
  - Reliability diagram for calibration (with ECE).
  - "What changed?" panel listing recent reassignments.
- Optional Platt-scaling calibrator — *deferred* (`specs/deferred.md`); the
  calibration diagram ships so miscalibration is visible.
- Flower exposed at `:5555` for queue inspection.

**Done when:** review a few hundred detections across model versions; the
metrics page shows a clear accuracy story over time and per class.

## Phase 7 — Polish & operations (S) — ✅ implemented

- Disk-usage UI (`/system/disk`); manual "purge frames older than" tool
  (`POST /system/purge-frames` → `vd.purge_frames`). `DELETE /clips/{id}` →
  `vd.delete_clip` rounds out disk management.
- Configurable settings (`/settings`) writes to `settings_kv`; a DB-override
  layer (`vd_db.load_effective_settings`) overlays env defaults so worker/API
  jobs honour edits on the next task — no restart.
- Performance pass: labeling UI prefetches the next queue frame for instant
  `J`-navigation. (`GET /system/queue` stays deferred — Flower covers it.)
- E2E smoke: an API-level integration test (`test_smoke_pipeline.py`) walks
  ingest → label → metric. Browser E2E (Playwright) was **deferred** — a real
  run needs the full GPU stack, which isn't CI-gateable.
- Documentation: README + `docs/runbook.md` (ops + troubleshooting).

## Phase 8 — External integration API (M) — ✅ implemented

Goal: two upstream apps (a UniFi Protect motion archiver and a family-video
archiver) can submit a video and be told who/what is in it.

- New `intake/` directory + `VD_INTAKE_DIR` (spec 02); not watched by
  `ingest-watcher`.
- `clips` gains `source` / `external_id` / `callback_url` / `external_metadata`
  / `canonical_clip_id`; new `webhook_deliveries` table + `delivery_status`
  enum (spec 03). One Alembic migration.
- `routers/jobs.py`: `POST /api/jobs` (path-reference submit, idempotent on
  `(source, external_id)`, intake-path validation) and `GET /api/jobs/{id}`
  (status + result payload) — spec 04 §Jobs.
- `vd.ingest_video` accepts a pre-created `clip_id`; SHA-collision on the job
  path sets `canonical_clip_id` (spec 05).
- `vd.deliver_callback` task: POSTs the result to `callback_url` on
  `clip.done` / `clip.failed`, retried + ledgered via `webhook_deliveries`.
- This is a backend/integration phase — no UI work. The `/clips` page may
  optionally show the `source` of a clip.

**Done when:** an external app writes a video to `intake/`, calls
`POST /api/jobs`, and receives a webhook (or polls `GET /api/jobs/{id}`)
carrying the detections + the who/what roll-up for that clip.

## Post-Phase-8 — Bulk labeling (S)

Goal: turn the per-frame, per-detection review flow into N decisions per
click, without changing the existing single-detection path.

- New endpoints in `routers/labeling.py`: `GET /predicted-groups`,
  `GET /predicted-group-detections`, `POST /bulk-review`. New
  `GET /clips/{id}/detections` + `GET /clips/{id}/class-summary` in
  `routers/clips.py`. Shared audit-row builder lifted to
  `services/audits.py` so bulk and per-detection writes produce
  byte-identical ledger rows (spec 04 §Labeling).
- New web routes `/labeling/groups` (predicted-subclass confirmation
  queue) and `/labeling/clips/:id` (clip-scoped tile grid), plus a
  `LabelingTabs` strip on the existing queue page and a `Bulk-label`
  button on the clip-detail page (spec 08 §Bulk labeling).
- Shared `<DetectionTileGrid>` with click / shift-click range / select-all
  / clear multi-select, reusing the existing `/api/detections/{id}/crop`
  cache.

**Done when:** open `/labeling/groups`, expand a high-confidence group,
hit Apply, and the `detection_audits` ledger gains one row per affected
detection while the per-class metrics page reflects the new accuracy.

## Cross-cutting workstreams

These run alongside the phases, not as discrete milestones:

- **Tests** — unit + integration at each phase; refuse to call a phase
  "done" without meaningful tests.
- **Migrations discipline** — every schema change goes through Alembic;
  no manual `psql` ALTERs.
- **Logging** — structured logs from day one; orjson encoder; request id
  propagated from API → SSE → tasks where reasonable.
- **Backups** — by Phase 5 the model store + DB is valuable; add a
  documented `pg_dump` + `tar data/` cron.

## What is "MVP"?

Phases 0–4 form a usable system: ingest, detect COCO objects, recognize
specific people, hand-label sub-classes, see corrections accumulate.

Phases 5–6 turn it from "useful for browsing video" into "trainable system
that gets smarter with use." This is where the requirement to track
"accuracy of automatic assignments over time" is fully delivered.

Phase 7 is polish — useful but interruptible.

## Risks

| Risk                                              | Mitigation                                           |
|---------------------------------------------------|------------------------------------------------------|
| NVIDIA Container Toolkit setup friction           | Document exact versions in spec 02; provide gpu-check |
| Catastrophic forgetting during YOLO fine-tune     | Keep COCO examples in mix; mAP regression guard      |
| Embeddings index growth (millions of detections)  | HNSW handles it; revisit at 10M; pgvector partitioning by class as escape hatch |
| Frame storage filling the disk                    | dedup'd near-duplicates pruned by `vd.dedup_clip_frames`; manual purge UI for older clips |
| Single-user assumptions hold across iterations    | Keep auth-shaped seams (`current_user` dependency stub) so we can add later if needed |
| `@nxlv/python` + UV friction                      | Fallback to `nx:run-commands` per project            |

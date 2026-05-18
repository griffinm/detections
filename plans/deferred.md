# Deferred items

A running registry of work consciously **deferred** during Phases 0–6 —
features that were planned but cut from a phase's scope, plus known tech debt.
Each entry says *what*, *why it was deferred*, and *where it would live*.

When you pick one of these up: implement it, then delete its entry here and
tick the relevant plan doc.

## Worker / ML

- **CPU worker image can't be lean** — `docker/worker/Dockerfile`'s `cpu`
  target installs only `torch` (no `vd-ml`), but `worker/tasks/__init__.py`
  imports *every* task module eagerly, and the GPU task modules pull
  `vd_ml` (→ ultralytics, insightface, transformers, sklearn) at import time.
  So the lean `cpu` image crashes on startup with `ModuleNotFoundError:
  vd_ml`. *Current workaround:* the server deploy builds `vd-worker-cpu` from
  the `gpu` target (see `docker/server-compose.yml`) — queue isolation is kept
  (`-Q cpu`, no GPU device) but the image is heavy. *Proper fix:* make the
  GPU task modules defer their `from worker.models import …` / `from vd_ml
  import …` into the task bodies (and/or lazy `vd_ml/__init__.py`), so the
  `cpu` image can drop the ML stack. *Where:* `apps/worker/src/worker/tasks/*`,
  `apps/worker/src/worker/models.py`, `libs/python/ml/src/vd_ml/__init__.py`.
  (plan 02/05)

- **`vd.backfill_detections`** — re-run detection over historical kept frames
  against a newly activated model (incl. an `auto_backfill_on_new_model`
  setting / a "reprocess" button). *Why:* Phase 5 scoped to forward-only — new
  clips use the new model automatically. *Where:*
  `apps/worker/src/worker/tasks/backfill_detections.py` (the task is already
  routed to the `gpu` queue in `vd_tasks/app.py`).

- **Per-class mAP regression guard** in `vd.finetune_yolo` — only the global
  aggregate guard (`mAP50-95 ≥ prev − 0.01`) is implemented. *Why:* Phase 5
  kept the guard simple. *Where:* `apps/worker/src/worker/tasks/finetune_yolo.py`
  — needs per-class val metrics out of Ultralytics. (plan 06)

- **Per-class oversampling** in the YOLO dataset builder — a 100-label custom
  class is swamped by thousands of COCO labels. *Why:* not needed for the
  first custom class. *Where:* `apps/worker/src/worker/dataset.py`. (plan 06)

- **Hard-negative mining** for sub-class assignment — feed rejected kNN matches
  (rejection audits) into the classifier as negatives at retrain. *Where:*
  `train_subclass_classifier`. (plan 06 open question)

- **`status='failed'` clip row for ingest failures** — `vd.ingest_video` now
  quarantines a permanently-failing source video to `failed/` so the inbox
  watcher stops looping on it, but writes no `clips` row (ingest may fail
  before any row exists, e.g. a corrupt file that breaks `ffprobe`). A failed
  ingest is therefore invisible in the UI. *Why:* needs a place to surface
  row-less failures — either a synthetic `clips` row keyed on the file SHA or
  a separate `ingest_failures` table. *Where:*
  `apps/worker/src/worker/tasks/ingest.py`. (plan 05)

## Metrics & observability

- **`daily_metrics` materialized view + nightly refresh** — Phase 6 metrics are
  computed on-the-fly, which is instant at single-user scale. At larger scale,
  materialize the daily roll-up. *Needs:* an Alembic migration creating the
  `MATERIALIZED VIEW`, a Celery-beat process (a new `docker-compose` service),
  and a `vd.refresh_daily_metrics` task (nightly + after retrains). (plan 03/06)

- **Platt-scaling calibrator** for YOLO confidence scores — Phase 6 ships the
  calibration *diagram* (ECE + reliability plot) so miscalibration is visible,
  but not the fitter. *Where:* fit on reviewed scores, store as a
  `model_versions` row (`kind='classifier'`, `target_class_id=NULL`), apply as
  a post-processing step in `detect_frame_batch`. (plan 06)

- **Detector precision/recall metrics (false-positive rate)** — `/metrics`
  measures *classification* accuracy over reviewed, non-deleted, model-produced
  detections (`predicted_* == current_*`). A false positive handled by deleting
  the detection sets `deleted_at`, which drops it from every metrics filter — so
  spurious detections never register as the model "getting it wrong", and the
  detector's precision is invisible. *Needs:* count `user_delete` audits (or
  deleted model-produced detections) as false positives, and missed objects
  (user-drawn `source='user'` boxes) as false negatives, to derive detector
  precision/recall alongside the existing classification accuracy. *Where:*
  `apps/api/src/api/routers/metrics.py`; the signal already exists in
  `detection_audits` + `detections.deleted_at`/`source`. (plan 06)

- **`GET /api/system/queue`** endpoint — Celery queue depths via `inspect`, and
  a **`vd.heartbeat`** periodic task writing worker liveness to Redis. *Why:*
  Flower (`:5555`) already covers live queue inspection. *Where:*
  `apps/api/src/api/routers/system.py` + a beat-scheduled task. (plan 04/05)

## Labeling UI

- **`recent corrections` labeling-queue strategy** — surface unreviewed frames
  visually similar to a recently corrected detection, as a pgvector kNN over
  that detection's embedding. *Why:* the `lowconf`, `unreviewed`, and
  class-targeted strategies shipped; this one needs a similarity query seeded
  from a correction and is disproportionately large. *Where:*
  `apps/api/src/api/routers/labeling.py`. (plan 08)

## Testing

- **Browser E2E (Playwright)** — Phase 7 shipped an API-level smoke test
  (`apps/api/tests/test_smoke_pipeline.py`) instead. A faithful browser E2E of
  ingest → label → metric needs the full stack incl. a GPU + ffmpeg, which is
  slow and not CI-gateable. *Where:* a new `apps/web` `e2e` target +
  `playwright.config.ts`. (plan 09)

## Tooling & CI debt

These pre-date Phase 4 and block a clean `nx run-many -t lint typecheck test`:

- **`libs/python/db/src/vd_db/base.py`** — a ruff `F401` (`typing.Any`) and an
  unsorted import block.
- **`apps/web` has no `eslint.config.js`** — ESLint 9 requires flat config, so
  `nx lint web` fails repo-wide.
- **`ruff` / `mypy` are not declared as dependencies** anywhere, so the nx
  `lint` / `typecheck` targets (`uv run ruff` / `uv run mypy`) cannot spawn
  them without a manual `uv tool install`.

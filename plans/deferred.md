# Deferred items

A running registry of work consciously **deferred** during Phases 0–6 —
features that were planned but cut from a phase's scope, plus known tech debt.
Each entry says *what*, *why it was deferred*, and *where it would live*.

When you pick one of these up: implement it, then delete its entry here and
tick the relevant plan doc.

## Worker / ML

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

- **`GET /api/system/queue`** endpoint — Celery queue depths via `inspect`, and
  a **`vd.heartbeat`** periodic task writing worker liveness to Redis. *Why:*
  Flower (`:5555`) already covers live queue inspection. *Where:*
  `apps/api/src/api/routers/system.py` + a beat-scheduled task. (plan 04/05)

## Labeling UI

- **On-canvas "original → current" chip** on the selected detection
  (e.g. "person → Mallory"). *Why:* the Konva canvas renders no text labels
  yet; the sub-class is shown in the left rail / class picker instead. *Where:*
  `apps/web/src/components/labeling/LabelingCanvas.tsx`. (plan 08)

- **Inline "+ New sub-class"** in the labeling class picker — sub-class CRUD
  currently lives only on the `/classes/:id` page. *Where:*
  `apps/web/src/components/labeling/ClassPicker.tsx`. (plan 08)

- **Labeling-queue strategies** beyond `lowconf` — `unreviewed` (newest first),
  `recent corrections` (kNN over a corrected detection's embedding), and
  class-targeted. *Where:* `apps/api/src/api/routers/labeling.py`. (plan 08)

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

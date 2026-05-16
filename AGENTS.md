# video-detection

Self-hosted application that ingests video clips from a watched folder,
extracts 1 frame per second, detects objects, recognizes specific people /
animals as named sub-classes, and tracks how well its automatic assignments
hold up against human review over time. Single user, single host, single
NVIDIA GPU.

## Status

**Planning complete; no implementation yet.** The architecture, schema,
APIs, ML approach, and UI design are specified in `./plans/`. There is no
code in the repo yet beyond this file. Start with `plans/09-milestones.md`
when picking up work.

## Read the plans first

`./plans/` is the source of truth. Read the relevant plan before working in
a subsystem, and **update the plan in the same change** when a decision
shifts. Plans must not silently fall out of sync with code.

| File | When to read it |
|------|-----------------|
| `plans/00-overview.md`            | Always — architecture, glossary, locked-in decisions |
| `plans/01-monorepo-and-tooling.md`| Adding/restructuring projects, lint/test config       |
| `plans/02-infra-and-config.md`    | docker-compose, GPU, env vars, folder layout          |
| `plans/03-data-model.md`          | Schema changes (always go through Alembic)            |
| `plans/04-backend-api.md`         | FastAPI routers, schemas, OpenAPI/client codegen      |
| `plans/05-worker-pipeline.md`     | Celery tasks, ffmpeg, model inference flow            |
| `plans/06-ml-training.md`         | YOLO/InsightFace/DINOv2, fine-tuning, accuracy semantics |
| `plans/07-frontend-foundation.md` | Web app shell, theming, routing, API client           |
| `plans/08-labeling-ui.md`         | Bbox canvas, hotkeys, sub-class examples              |
| `plans/09-milestones.md`          | Phase sequencing — what to build next                 |

## Locked-in stack

| Area              | Choice                                                       |
|-------------------|--------------------------------------------------------------|
| Monorepo          | NX with `@nxlv/python` plugin, UV as the Python pkg manager  |
| Node/JS           | pnpm workspace, Node 20, TypeScript 5 strict                 |
| Python            | 3.12                                                         |
| Backend           | FastAPI + SQLAlchemy 2.x async + Alembic                     |
| Database          | Postgres 16 with `pgvector` (one DB, vectors on `detections`) |
| Queue             | Celery + Redis (queues: `cpu`, `gpu`, `train`)               |
| Object detector   | Ultralytics YOLOv11-L                                        |
| Face det/embed    | InsightFace `buffalo_l` (RetinaFace + ArcFace, 512-d)        |
| Generic embedder  | DINOv2 small (`facebook/dinov2-small`, 768-d)                |
| Frontend          | React 18 + Vite + Tailwind + shadcn/ui (light + dark)        |
| Bbox canvas       | `react-konva`                                                |
| Routing/state     | React Router 7 + TanStack Query 5 + Zustand                  |
| Ingest            | `watchdog` folder watcher (`apps/ingest-watcher`)            |
| Auth              | None (single-user, local network)                            |
| GPU               | Worker container with NVIDIA Container Toolkit               |

If you find yourself reaching for an alternative, update plan 00 with the
reason before changing code.

## Repo conventions (once code exists)

- Schema changes go through **Alembic migrations** — never hand-altered.
- Python deps are managed by **UV per project** (each `apps/*` and
  `libs/python/*` has its own `pyproject.toml`); shared libs are path deps.
- Configuration is read once via `libs/python/settings.Settings`
  (pydantic-settings, env prefix `VD_`). Don't read `os.environ` directly.
- The API never enqueues heavy work synchronously — it writes to DB and
  sends a Celery task on the appropriate queue.
- Tasks are **idempotent**: SHA dedup at ingest, `(clip_id, frame_index)`
  upsert at extract, skip-if-done on detect/recognize/embed.
- Frame coords stored normalized `{x,y,w,h}` in 0..1; convert to pixels
  only at the boundary (canvas, ffmpeg crop, YOLO label files).
- `detection_audits` is **insert-only**. Every model prediction and every
  user correction writes one row. This is what `metrics` queries from.
- Models are referenced by `model_versions.id`, never by file path
  outside the registry. Only one `is_active=true` per `(kind, target_class_id)`.

## NX targets (canonical)

Per Python project: `lint` (ruff check), `format` (ruff format), `typecheck`
(mypy), `test` (pytest), `serve` (uvicorn / celery / watcher loop).
Per JS project: `lint` (eslint), `format` (prettier), `typecheck`
(tsc --noEmit), `test` (vitest), `build`, `serve` (Vite).

Aggregates: `nx run-many -t lint typecheck test` (CI gate),
`nx affected -t lint test build` (PRs).

## Working with this codebase

- For broad questions or refactors that touch multiple plans, propose the
  plan diff first (which docs change, how), then implement.
- For UI/frontend changes, run the dev server and exercise the feature
  end-to-end — type-check + tests verify code, not feature correctness.
- Don't add backwards-compatibility shims for things that don't exist yet.
  This codebase is greenfield.
- Don't add comments that restate code. Reserve comments for non-obvious
  *why* — hidden constraint, subtle invariant, workaround for a specific
  upstream bug.
- The user prefers terse responses and recommendation-led options when
  asked to choose. Don't ask 6 small questions when 2 architectural ones
  would do.

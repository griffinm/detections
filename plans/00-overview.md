# 00 — System Overview

This is the top-level plan. The numbered companion plans (01–09) drill into each
subsystem. Read this one first; the others assume its vocabulary and assumptions.

## Goal

Build a self-hosted application that ingests video clips from a folder, extracts
1 frame per second, detects objects (people, faces, cars, dogs, bears, and
user-defined classes such as deer), recognizes specific individuals where
possible (e.g., a particular person named "Mallory"), and tracks how well its
automatic assignments hold up against human review over time.

Single user, single GPU, single host. No multi-tenancy, no cloud auth.

## Locked-in decisions

| Area              | Choice                                                       |
|-------------------|--------------------------------------------------------------|
| Monorepo          | NX with `@nxlv/python` plugin, UV as the Python pkg manager  |
| Backend           | FastAPI                                                      |
| ORM / migrations  | SQLAlchemy 2.x (async) + Alembic                             |
| Database          | Postgres 16 with `pgvector` extension                        |
| Queue             | Celery + Redis broker/result backend                         |
| Object detector   | Ultralytics YOLO (v11)                                       |
| Face det/embed    | InsightFace (RetinaFace + ArcFace ResNet50)                  |
| Generic embedder  | DINOv2 small (for non-face sub-class kNN)                    |
| Vector storage    | `pgvector` columns on `detections` table                     |
| Frontend          | React + Vite + TypeScript + Tailwind + shadcn/ui             |
| Theming           | Light + dark via Tailwind `class` strategy + shadcn tokens   |
| Ingest            | Folder watcher (`watchdog`) on a configured input directory  |
| Auth              | None (single-user, local network)                            |
| GPU access        | Worker container with NVIDIA Container Toolkit               |
| Bbox UI           | Confirm / correct / draw new                                 |
| Custom classes    | Hand-label N examples → fine-tune YOLO → hot-swap weights    |

## Components

```
                ┌──────────────────────┐
                │   Video drop folder  │
                │ /data/videos/inbox   │
                └─────────┬────────────┘
                          │ (watchdog inotify)
                          ▼
                ┌──────────────────────┐
                │   ingest-watcher     │  (host or container process)
                │   small Python loop  │
                └─────────┬────────────┘
                          │ enqueue ingest_video(path)
                          ▼
   ┌──────────────────────────────────────────────────────────┐
   │                    Celery (Redis broker)                 │
   │                                                          │
   │  queue: cpu        queue: gpu          queue: train      │
   │  ─ ingest          ─ detect_frame      ─ retrain_classfr │
   │  ─ extract_frames  ─ recognize_face    ─ finetune_yolo   │
   │  ─ assign_subcls   ─ ...                                  │
   └─────────┬──────────────────────────────────────┬─────────┘
             │                                      │
             ▼                                      ▼
   ┌──────────────────┐                  ┌──────────────────────┐
   │   Postgres +     │  ◀─ SQLAlchemy ─▶│       FastAPI        │
   │     pgvector     │                  │       /api/*         │
   └──────────────────┘                  └─────────┬────────────┘
             ▲                                      │
             │                                      ▼
   ┌──────────────────┐                  ┌──────────────────────┐
   │  /data/frames/   │  ◀─ static ──────│  React frontend      │
   │  (JPEGs by clip) │                  │  (Vite dev / nginx)  │
   └──────────────────┘                  └──────────────────────┘
```

Frames are written to disk and served as static files; metadata + detections +
embeddings live in Postgres.

## Data lifecycle

1. **Drop**: a video lands in `/data/videos/inbox/`.
2. **Ingest**: watchdog enqueues `ingest_video`, which probes with ffprobe and
   inserts a `clips` row (status=`pending`). Idempotent by content hash.
3. **Extract**: `extract_frames` runs ffmpeg at 1 FPS, writes JPEGs under
   `/data/frames/<clip_id>/`, inserts a `frames` row per frame.
4. **Detect**: `detect_frame` runs YOLO on each frame; produces `detections`.
   - If the frame yields no detection above the configured confidence threshold
     for any active class, mark `frames.kept=false` and delete the JPEG.
5. **Recognize** (faces only, for now): for each person-class detection, run
   InsightFace, store the 512-d embedding on the detection.
6. **Sub-class assign**: kNN the embedding against the class's
   `subclass_examples` table; if best match exceeds threshold, set
   `predicted_subclass_id` + `confidence_subclass`.
7. **Review**: user opens the labeling UI, confirms / corrects / draws boxes
   and class+subclass labels. The corrections become ground truth and feed
   the audit log.
8. **Retrain (optional, background)**:
   - When a custom class accumulates ≥ N labels, queue a YOLO fine-tune.
   - When a sub-class accumulates ≥ M new labels, retrain the per-class
     linear-on-embeddings classifier.
9. **Cleanup**: original video can be moved to `/data/videos/processed/` (or
   deleted by the user); frames stay until the user purges them.

## Plan index

- [01 — Monorepo & tooling](./01-monorepo-and-tooling.md) — NX layout, UV,
  shared libs, lint/test/CI.
- [02 — Infra & configuration](./02-infra-and-config.md) — docker-compose,
  GPU access, volumes, env vars, folder layout.
- [03 — Data model](./03-data-model.md) — Postgres schema, pgvector,
  Alembic migrations.
- [04 — Backend API](./04-backend-api.md) — FastAPI routers, schemas,
  OpenAPI client codegen, SSE for live progress.
- [05 — Worker pipeline](./05-worker-pipeline.md) — Celery tasks, watcher,
  ffmpeg, idempotency, queue topology.
- [06 — ML & training](./06-ml-training.md) — YOLO, InsightFace, DINOv2,
  custom-class fine-tune, accuracy tracking.
- [07 — Frontend foundation](./07-frontend-foundation.md) — Vite + shadcn
  setup, theming, routing, API client.
- [08 — Labeling UI](./08-labeling-ui.md) — bbox canvas, draw/edit, hotkeys,
  sub-class examples, review queue.
- [09 — Milestones](./09-milestones.md) — phased delivery, dependencies,
  what counts as MVP.

## Glossary

- **Clip**: a single ingested video file.
- **Frame**: a JPEG extracted from a clip at 1 FPS.
- **Class**: a top-level object category (`person`, `car`, `dog`, `bear`,
  `deer`, …). May be COCO-builtin or user-defined.
- **Sub-class**: a named instance under a class (`Mallory` under `person`,
  `Buddy` under `dog`). Optional.
- **Detection**: one bounding box on one frame with a class (and optionally a
  sub-class), plus confidences and an embedding.
- **Sub-class example**: a detection a user has marked as a canonical example
  of a sub-class, used as a kNN reference.
- **Ground truth**: a detection's user-confirmed state. Distinct from the
  model's original prediction, which we keep around for accuracy tracking.

## Open questions (deferred — sensible defaults will go in the plans)

- **Discard threshold**: "no objects" = max detection confidence < 0.25 across
  all active classes. Default 0.25; user-tunable.
- **Custom-class fine-tune threshold**: default 100 labeled examples per
  custom class.
- **Sub-class retrain threshold**: default 25 new labeled examples since last
  train.
- **Frame storage**: JPEG quality 90, original resolution, no downscale.
- **Near-duplicate frames**: not handled in v1; can add perceptual-hash dedup
  later if needed.
- **Backfill on new model**: optional, user-triggered.

If any of these defaults are wrong for your use case, flag them now —
otherwise we'll proceed with the numbers above.

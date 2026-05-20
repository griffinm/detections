# Operations runbook

Day-to-day operation and troubleshooting for a single-host, single-GPU
video-detection deployment. For architecture and design rationale see
`specs/`; for setup see `README.md`.

## Services

| Service          | Where it runs            | Start                          |
|------------------|--------------------------|--------------------------------|
| Postgres + Redis | docker-compose           | `docker compose -f docker/docker-compose.yml up -d postgres redis` |
| Worker (cpu)     | host (dev) / docker-compose | part of `pnpm dev`; or `docker compose -f docker/docker-compose.yml up -d worker-cpu` |
| Worker (gpu)     | docker-compose           | `pnpm gpu` (= `docker compose -f docker/docker-compose.yml up --build worker-gpu`) |
| Ingest watcher   | docker-compose or host   | `nx run ingest-watcher:serve`  |
| API              | host (dev) / `full` profile | `nx run api:serve`          |
| Web              | host (dev)               | `nx run web:serve`             |
| Flower           | docker-compose           | bundled — `http://localhost:5555` |

`pnpm dev` (or `./tools/scripts/dev.sh`) brings up Postgres + Redis and the
four dev servers together. Ctrl-C stops the dev servers; Postgres/Redis keep
running. The dev worker consumes the `cpu` queue only — run `pnpm gpu` in a
second terminal for the containerized GPU worker (`gpu` + `train` queues),
which has CUDA access via the NVIDIA Container Toolkit. Without it, clips sit
in `detecting`.

## Routine operations

### Disk management

Frames accumulate at ~1 JPEG/second of video. Monitor and reclaim space from
the **System** page (`/system/disk`):

- **Disk usage** — per-directory bytes + file counts for `inbox`, `processed`,
  `frames`, `models`, plus total/free on the volume.
- **Purge old frames** — deletes the JPEGs of frames whose clip is older than
  N days (`POST /system/purge-frames` → the `vd.purge_frames` Celery task).
  Frame and detection rows — and the `detection_audits` ledger — are kept; only
  the images are removed, so metrics stay intact.
- **Delete a clip** — the Delete button on a clip's detail page enqueues
  `vd.delete_clip`, which removes the frame directory, the source video (iff
  `delete_processed_videos`), and cascades the frame/detection rows.

Cron-able equivalent of the purge tool:

```bash
curl -fsS -X POST http://localhost:8000/api/system/purge-frames \
  -H 'Content-Type: application/json' -d '{"older_than_days": 30}'
```

### Settings

The `/settings` page edits tunables stored in the `settings_kv` table —
confidence thresholds, batch sizes, sampling FPS, training thresholds, and
retention flags. Overrides overlay the `.env` defaults via
`vd_db.load_effective_settings`, which every worker/API job calls per task, so
a change takes effect on the **next job** with no restart. "Reset" clears the
override and returns the setting to its env default. Paths, URLs, and model
identity are not editable here — change those in `.env` and restart.

### Backups

Bind-mounted data lives on the host filesystem. By Phase 5 the model store +
DB are valuable — back them up:

```bash
# Postgres dump + a tar of the data tree (videos, frames, models).
docker compose -f docker/docker-compose.yml exec -T postgres \
  pg_dump -U vd video_detection | gzip > backup/db-$(date +%F).sql.gz
tar czf backup/data-$(date +%F).tar.gz data/
```

Run nightly from cron. Restore: `gunzip -c db-*.sql.gz | psql` into a fresh
database, then untar `data/`.

## Deploying

The app runs on the `layla` server. Images are **built locally** and pushed
to the private registry at `nas.malfin.com:10100`; the server only pulls
and restarts. Redeploy with:

```bash
./tools/scripts/deploy.sh
```

The script builds the four service images (api, web, worker, ingest-watcher)
tagged with the short git hash, pushes them to the registry, rewrites
`VD_API_IMAGE` / `VD_WEB_IMAGE` / `VD_WORKER_IMAGE` / `VD_WATCHER_IMAGE` in
`layla:~/docker/.env`, then runs `docker compose up -d --pull always` on
`layla`. The `vd-api` container runs `alembic upgrade head` on start, so
migrations need no manual step. `data/` on the server is untouched — bind
mounts already point there.

**One-time server setup** (before the first deploy):

```bash
scp docker/server-compose.yml layla:~/docker/compose/video-detections.yml
# Then on layla, add to ~/docker/.env:
#   VD_API_IMAGE=nas.malfin.com:10100/vd-api:placeholder
#   VD_WEB_IMAGE=nas.malfin.com:10100/vd-web:placeholder
#   VD_WORKER_IMAGE=nas.malfin.com:10100/vd-worker:placeholder
#   VD_WATCHER_IMAGE=nas.malfin.com:10100/vd-ingest-watcher:placeholder
#   VIDEO_DETECTION_DB_PASSWORD=...
# The placeholder image values are overwritten by the first deploy.
```

`VD_DEPLOY_HOST` overrides the SSH target (default `layla`); `VD_REGISTRY`
overrides the registry. See `specs/02-infra-and-config.md`
(§Production deployment) for the design rationale.

## Monitoring

- **Metrics page** (`/metrics`) — class accuracy over time, per-class
  precision/recall, calibration (ECE), recent reassignments.
- **Flower** (`http://localhost:5555`) — Celery queue depth, worker liveness,
  task history. The in-app `GET /system/queue` endpoint is deferred; use Flower.
- **Health** — `curl http://localhost:8000/api/system/health` → DB + Redis status.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Clip stuck in `pending` / `extracting` | cpu worker down, or no ffmpeg in the container | Check `worker-cpu` is up; confirm ffmpeg installed |
| Clip stuck in `detecting` | gpu worker down, or GPU unavailable | `nx run worker:gpu-check`; check `worker-gpu` logs |
| `torch.cuda.is_available()` is false | NVIDIA Container Toolkit / `runtime: nvidia` missing | See `specs/02-infra-and-config.md`; `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi` |
| Settings change has no effect | reading a job that started before the edit | Overrides apply to the *next* task — wait for the next job |
| Disk filling up | frames not pruned | Lower retention via `/settings`; purge from `/system` |
| Queue backlog grows | a fine-tune is starving inference | Fine-tunes run on the `train` queue; let it finish or scale the gpu worker |
| Migrations out of sync | schema drift after a pull | `uv run alembic upgrade head` from `libs/python/db` |
| API `/system/health` shows `error` | Postgres/Redis container down | `docker compose ... up -d postgres redis` |

## Quality gate

```bash
nx run-many -t lint typecheck test
```

Known pre-existing gaps in this aggregate are tracked in `specs/deferred.md`
(Tooling & CI debt).

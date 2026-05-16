# 05 — Worker Pipeline

## Goals

- Process a dropped video into kept frames + detections + sub-class assignments
  reliably and idempotently.
- Keep the single GPU saturated with detection / recognition work; do not
  waste it on ffmpeg.
- Pause-able and re-runnable: if the worker crashes mid-clip, restarting it
  resumes from the last completed step.
- Custom-class fine-tuning and per-class classifier retraining run on the
  same `train` queue, scheduled by user action or threshold trigger.

## Topology

Three Celery queues, two workers:

| Queue   | Worker     | Workload                                          |
|---------|------------|---------------------------------------------------|
| `cpu`   | worker-cpu | ingest, ffprobe, ffmpeg frame extraction, IO     |
| `gpu`   | worker-gpu | YOLO detection, InsightFace embed, DINOv2 embed  |
| `train` | worker-gpu | YOLO fine-tune, classifier retrain               |

The `gpu` worker has concurrency = 1 (one CUDA stream, one model in VRAM
at a time). The `cpu` worker has concurrency = N (default 2).

`train` shares the GPU worker; it's a separate queue so we can pause
training during interactive labeling sessions if needed (the user can
toggle a "no-train" mode in settings).

## Task contracts

Task *implementations* live in `apps/worker/src/worker/tasks/` (one module per
task, registered via `autodiscover_tasks`). `libs/python/tasks` (`vd_tasks`)
holds only the shared Celery app + queue routing, imported by both the worker
and the API. The API never imports task code — it dispatches via
`celery_app.send_task('vd.ingest_video', …)` (the `api.deps.enqueue` helper) to
keep its dep tree light.

### `vd.ingest_video(path: str) -> uuid`
- Compute sha256 of the file.
- If a `clips` row already exists with that hash, log "already ingested",
  move file to `processed/`, return the existing id.
- Otherwise: ffprobe for metadata, insert `clips` row with status=`pending`,
  schedule `vd.extract_frames` on the `cpu` queue.

Idempotency: hash check. Safe to retry. Failure → status `failed` + reason.

### `vd.extract_frames(clip_id: uuid)`
- Set clip status → `extracting`.
- Run ffmpeg:
  ```bash
  ffmpeg -hide_banner -i <src> -vf fps=1 -q:v 2 <frames_dir>/<clip>/frame_%06d.jpg
  ```
  We use `-q:v 2` to control JPEG quality (~92). Tunable.
- After ffmpeg completes, walk the output directory, insert a `frames` row
  per file with `detect_status='pending'` and `kept=true`. Use an upsert
  on `(clip_id, frame_index)` so partial runs converge.
- Schedule `vd.detect_frame_batch` tasks on the `gpu` queue (`VD_DETECT_BATCH_SIZE`
  frames per task, default 16, to amortize model warm-up).
- Set clip status → `detecting` (or straight to `done` if the clip yielded
  no frames).

Idempotency: the upsert + a per-frame status make this safely re-runnable.

### `vd.detect_frame_batch(frame_ids: list[uuid])`
- Load active YOLO model (process-level singleton; loaded once at worker boot).
- Read frame JPEGs from disk (parallel).
- Run YOLO `model.predict(images, conf=detection_min_confidence)`.
- For each frame:
  - If zero detections → set `frames.kept=false`, schedule
    `vd.prune_frame(frame_id)` on `cpu` (which deletes the file iff
    `delete_frames_without_objects` is set).
  - Else, insert a `detection` row per box: `source='model'`,
    `predicted_class_id` = lookup by yolo class index, `class_id` mirrors
    predicted at insert, `model_version_id` = active YOLO version,
    `confidence_class` = raw score.
  - Write a `detection_audits` row for each new detection with
    `reason='initial_prediction'`.
  - For person-class detections, schedule `vd.recognize_face(detection_id)`.
  - For any other detection that has at least one labeled sub-class in its
    class, schedule `vd.embed_object(detection_id)`.
- Set per-frame `detect_status='done'`.
- Publish `frame.detect.done` event to Redis pub/sub.
- After the batch, if no frame of the clip is still `detect_status='pending'`,
  set clip status → `done` and publish `clip.done`.

GPU streaming: the worker uses a process-level YOLO instance and reads
frames into a torch tensor in batches. Batching gives a 3-5× throughput
improvement vs per-frame inference.

### `vd.recognize_face(detection_id: uuid)`
- Load the detection's frame, crop the bbox.
- Run InsightFace: detect any face inside the crop (usually 0 or 1).
- If a face is found:
  - Compute the ArcFace embedding (vector(512)).
  - Store on `detections.face_embedding`.
  - Schedule `vd.assign_subclass(detection_id)`.
- If no face is found inside the person crop, leave embedding NULL and skip
  sub-class assignment.

### `vd.embed_object(detection_id: uuid)`
- Crop bbox, resize to 224×224.
- Run DINOv2 small (Hugging Face `facebook/dinov2-small`) → vector(768).
- Store on `detections.object_embedding`.
- Schedule `vd.assign_subclass(detection_id)`.

### `vd.assign_subclass(detection_id: uuid)`
- Look up class.
- If class has zero active sub-classes → no-op.
- Pick embedding to query: `face_embedding` if class==person and present;
  else `object_embedding`.
- kNN query against `subclass_examples` for this class (HNSW index on
  the matching embedding column): top-5 nearest example detections,
  **majority vote**, tie-break on mean cosine similarity. The detection
  itself is excluded so an example cannot self-confirm.
- If the winning mean similarity ≥ `subclass_min_confidence`, set
  `predicted_subclass_id` + `confidence_subclass`. Also set `subclass_id`
  (== predicted) unless the detection has already been user-reviewed.
- Write a `detection_audits` row (`reason='initial_prediction'`) and publish
  a `frame.updated` event.

### `vd.finetune_yolo(training_run_id: uuid)`
- The **API** creates the `training_runs` row (`status='queued'`) and enqueues
  the task; the task receives the run id. Triggered by:
  - `POST /training-runs { kind: 'yolo' }`
  - or automatically when the labeled dataset crosses
    `custom_class_finetune_threshold` (see `services/training_service.py`).
- Steps:
  1. Mark the run `running`; resolve the active YOLO checkpoint as the base.
  2. Build the YOLO dataset (`worker/dataset.py`): every ground-truth
     detection (`source='user' OR reviewed`) across all classes — so COCO
     classes are not forgotten — on frames whose JPEG survives. Symlink the
     frame JPEGs; write `<idx> <xc> <yc> <w> <h>` labels; split 80/10/10 by
     frame; write `data.yaml`.
  3. Train from the previous checkpoint via `vd_ml.train_yolo` in a worker
     thread; bridge per-epoch progress back as `training_run.update` events.
  4. Register a new `model_versions` row. **Regression guard:** activate it
     (via `vd_db.activate_model_version`) only if val mAP50-95 ≥ the previous
     active model's − 0.01 (skipped on the first-ever fine-tune). Activation
     deactivates the prior model and syncs `classes.yolo_class_index`.
  5. Mark the run `succeeded`/`failed`; broadcast `model.active_changed`.
- Training failures (OOM, bad data) are terminal — the run is marked `failed`
  and the task returns; no Celery retry.

### `vd.train_subclass_classifier(training_run_id: uuid)`
- The API creates the `training_runs` row (`kind='classifier'`,
  `target_class_id` set) and enqueues the task. Triggered by the user (a class
  page button) or automatically at `subclass_retrain_threshold` new labels.
- Pulls embeddings (face or object as appropriate) + sub-class labels from the
  class's reviewed detections and `subclass_examples`.
- Trains `LogisticRegression` (multinomial, L2) via scikit-learn
  (`vd_ml.train_subclass_classifier`); needs ≥2 labeled sub-classes.
- Persists as `joblib` at `models/classifiers/<class_id>/<run_id>.joblib`,
  writes a `model_versions` row, activates it (no regression guard).
- `vd.assign_subclass` then uses the active classifier (Regime B) in preference
  to kNN; kNN remains the bootstrap path when no classifier exists yet.

### `vd.backfill_embeddings(class_id: uuid)`
- Triggered when the first active sub-class is created for a class, or by the
  `POST /classes/{id}/rescan-subclasses` endpoint.
- Scans every live detection of `class_id`: those missing the relevant
  embedding are fanned out to `vd.recognize_face` / `vd.embed_object` (which
  chain into `vd.assign_subclass`); those already embedded go straight to
  `vd.assign_subclass`. This is what lets clips ingested *before* a sub-class
  existed still get auto-assigned.

### `vd.backfill_detections(model_version_id, since_clip_id?)`
- Re-runs detection over historical kept frames using the given model.
- Lower priority queue. Cancellable.

### `vd.purge_frames(older_than_days: int)` *(Phase 7, `cpu` queue)*
- Disk reclamation: deletes the JPEG of every frame whose clip is older than
  the cutoff and nulls `frames.path`. Frame + detection rows (and the audit
  ledger) are kept — only the images go. Triggered by `POST /system/purge-frames`.

### `vd.delete_clip(clip_id: uuid)` *(Phase 7, `cpu` queue)*
- Removes a clip: deletes the frame directory, deletes the source video iff
  `delete_processed_videos`, then issues a Core `DELETE` so the
  `ondelete=CASCADE` FKs drop frames + detections. Publishes `clip.deleted`.
  Triggered by `DELETE /clips/{id}`. Idempotent — a missing clip is a no-op.

## Folder watcher (`apps/ingest-watcher`)

Tiny standalone process. Implementation:

```python
# apps/ingest-watcher/src/watcher.py
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from celery import Celery
from vd_settings import Settings

settings = Settings()
celery_app = Celery(broker=settings.redis_url)

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}

class Handler(FileSystemEventHandler):
    def on_closed(self, event):
        path = Path(event.src_path)
        if path.suffix.lower() in VIDEO_EXTS:
            celery_app.send_task("vd.ingest_video", args=[str(path)], queue="cpu")

if __name__ == "__main__":
    obs = Observer()
    obs.schedule(Handler(), str(settings.inbox_dir), recursive=True)
    obs.start()
    # On startup, also scan for pre-existing files (idempotent enqueue):
    for p in settings.inbox_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
            celery_app.send_task("vd.ingest_video", args=[str(p)], queue="cpu")
    try:
        while True: time.sleep(1)
    finally:
        obs.stop(); obs.join()
```

Notes:
- We listen on `on_closed`, not `on_created`, to avoid acting on a file
  that's still being written (Linux `IN_CLOSE_WRITE`).
- If `on_closed` is not available on the host's filesystem (e.g., some FUSE
  mounts), fall back to a stable-size poll: schedule when size + mtime have
  been unchanged for ~3 seconds.
- The startup scan handles files that landed while the watcher was down.

## Idempotency & failure recovery

Each task is idempotent:
- `ingest_video`: SHA dedup.
- `extract_frames`: upsert on `(clip_id, frame_index)`.
- `detect_frame_batch`: skip frames whose `detect_status='done'`.
- `recognize_face` / `embed_object`: skip if embedding already non-null.
- `assign_subclass`: pure compute; safe to re-run; only updates if the
  detection has not been user-reviewed.

Failure handling:
- Retry policy: `autoretry_for=(SomeTransientError,)`, max_retries=3,
  exponential backoff, jitter.
- Permanent failures move the clip to `failed/` and set `status='failed'`
  with the error message. Visible in the UI; user can fix and re-enqueue.
- Dead-letter queue: failed tasks beyond max_retries are routed to a
  `dead` queue we can inspect via Flower.

## Configuration knobs (re-stated from plan 02)

- `VD_FRAME_FPS` — sample rate (default 1.0).
- `VD_DETECTION_MIN_CONFIDENCE` — discard threshold (default 0.25).
- `VD_SUBCLASS_MIN_CONFIDENCE` — sub-class cosine threshold (default 0.55).
- `VD_CUSTOM_CLASS_FINETUNE_THRESHOLD` — labels needed (default 100).
- `VD_SUBCLASS_RETRAIN_THRESHOLD` — labels needed (default 25).
- `VD_DELETE_FRAMES_WITHOUT_OBJECTS` — bool (default true).
- `VD_DELETE_PROCESSED_VIDEOS` — bool (default false).

## Observability

- Each task logs structured JSON (orjson) with `task_id`, `clip_id`,
  `frame_id`, timing.
- Celery sends task lifecycle to Redis pub/sub channel `events:tasks` →
  forwarded as SSE.
- Flower at `:5555` for queue depth, worker liveness, task history.
- Periodic task `vd.heartbeat` writes worker status to Redis for the
  `/system/queue` API.

## Open questions

- **Frame batching**: 16 per batch is the starting point. Tune up if GPU
  underutilized (`nvidia-smi`) — typically 32–64 is sweet spot on a single
  consumer GPU at 960px.
- **GPU OOM safety net**: trap CUDA OOM in `detect_frame_batch` and halve
  the batch size on retry. Log a warning so we can permanently lower the
  default.
- **Process restart cost**: loading YOLO+InsightFace+DINOv2 weights once
  costs ~5–10s. Celery worker `--max-tasks-per-child` should be disabled or
  set very high so we don't reload per task.

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

### `vd.ingest_video(path: str, clip_id: uuid | None = None) -> uuid`

Two callers: the folder watcher passes only `path` (a watched `inbox/` drop);
`POST /api/jobs` passes `path` **and** a pre-created `clip_id` (spec 04 §Jobs).

- Compute sha256 of the file.
- If another `clips` row already exists with that hash:
  - **Watcher path** (`clip_id is None`) — log "already ingested", move the
    file to `processed/`, return the existing id.
  - **Job path** — set this row's `canonical_clip_id` to the existing clip and
    return; do not extract frames again. The job's result and callback resolve
    through `canonical_clip_id`; the canonical clip's completion handler fans
    the callback out to it (see `vd.detect_frame_batch`).
- Otherwise: ffprobe for metadata. If `clip_id` was supplied, UPDATE that row
  (status stays `pending`; fill in sha256/size/duration/dimensions/codec);
  else INSERT a fresh `clips` row (`source='watch'`). Schedule
  `vd.extract_frames` on the `cpu` queue.

Idempotency: hash check. Safe to retry. Failure → status `failed` + reason; the
failure handler fires a `clip.failed` callback for any clip with a
`callback_url` (see Failure handling).

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
- For each frame, compute a 64-bit perceptual hash (`imagehash.phash`) of the
  JPEG and store it in `frames.phash` (8 bytes). CPU-only and cheap — it runs
  here on the `cpu` worker, in the same directory walk as the row insert. The
  hash is the similarity signal for near-duplicate pruning (see
  `vd.dedup_clip_frames`).
- Schedule `vd.detect_frame_batch` tasks on the `gpu` queue (`VD_DETECT_BATCH_SIZE`
  frames per task, default 16, to amortize model warm-up).
- If `VD_COMPRESS_PROCESSED_VIDEOS` is set, schedule `vd.compress_video` on
  `gpu` too — it FIFOs behind detect so it doesn't delay detection latency.
- Set clip status → `detecting` (or straight to `done` if the clip yielded
  no frames).

Idempotency: the upsert + a per-frame status make this safely re-runnable.

### `vd.compress_video(clip_id: uuid)` *(`gpu` queue)*

Re-encodes the source video at `clip.final_path` to HEVC using the GPU's
NVENC engine, then atomically replaces the original. Disk reclamation
without losing the file (`vd.reextract_frames` still works against the
compressed clip).

- Skip if `clip.codec` is already `'hevc'` / `'h265'`, the row is missing,
  or `final_path` doesn't resolve to a file — keeps retries and
  `vd.reextract_frames` re-runs idempotent.
- Run ffmpeg (`hevc_nvenc`, `-rc vbr -cq <VD_COMPRESS_CRF> -b:v 0`,
  `-preset p5`, `-c:a copy`) writing to `<stem>.compress.tmp<ext>` next to
  the original. Resolution and frame rate are preserved (no `-vf`/`-r`).
- On non-zero exit: unlink the tmp, raise — Celery retries up to
  `max_retries`. The original is never touched until the encode succeeds.
- On success: `os.replace(tmp, final_path)` (atomic on POSIX), then update
  `clips.codec='hevc'` and `clips.size_bytes` from the new file's `stat`.
- Publish `clip.compressed` with `{clip_id, size_before, size_after}`.
- Compression is non-fatal: a clip whose compress task exhausts retries
  stays usable — the detect/recognize/embed pipeline runs from the JPEG
  frames and is independent of the source video format.

Runs on `gpu` because `hevc_nvenc` needs the NVIDIA driver mounted by the
container toolkit (the `cpu` worker has no GPU access). NVENC is a
dedicated silicon block separate from the CUDA cores, so it doesn't
contend with YOLO for compute — but the worker's `concurrency=1`
serializes them at the Celery level. Splitting compression onto its own
queue is deferred (see `specs/deferred.md`).

### `vd.detect_frame_batch(frame_ids: list[uuid])`
- Load active YOLO model (process-level singleton; loaded once at worker boot).
- Read frame JPEGs from disk (parallel).
- Run YOLO `model.predict(images, conf=detection_min_confidence, device=0)`.
  The device is pinned to CUDA 0: `vd_ml.predict_batch` rejects a missing GPU
  with a `RuntimeError` rather than letting Ultralytics fall back to CPU at
  ~10× the latency.
- For each frame:
  - Frames with zero detections stay `kept=true` and on disk — YOLO can miss
    objects, and the labeling UI lets the user add a box manually after the
    fact. Only `vd.dedup_clip_frames` flips `kept=false` and unlinks JPEGs.
  - Insert a `detection` row per box: `source='model'`,
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
  set clip status → `done`, publish `clip.done`, schedule
  `vd.dedup_clip_frames(clip_id)` on the `cpu` queue, and — for this clip *and*
  every clip whose `canonical_clip_id` points at it — schedule
  `vd.deliver_callback` on `cpu` for each that has a `callback_url`. Dedup is
  an off-critical-path cleanup pass — the clip is `done` regardless of whether/
  when it runs.

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

### `vd.predict_user_detection(detection_id: uuid)` *(`gpu` queue)*
- Triggered by `POST /detections/{id}/predict` after the labeling UI's
  ~1 s debounce on drawing or resizing a user-source box. Skips if the
  detection is soft-deleted or `source != 'user'`.
- Load the active YOLO model and run `predict_batch` on the **full**
  frame JPEG (YOLO degrades on tight crops because it's trained with
  contextual surroundings — one extra inference per drawn box is cheap
  enough to pay for the accuracy).
- IoU-match each YOLO box against `detection.bbox` (normalized
  `{x,y,w,h}`); keep the highest-IoU candidate where IoU ≥ 0.3.
- Write `predicted_class_id` + `confidence_class`. Set `class_id` to the
  predicted class **only when it was null** — a class the user already
  picked wins. If `class_id` ends up set, chain `vd.recognize_face` /
  `vd.embed_object` (same logic as `vd.detect_frame_batch`) so the
  sub-class pipeline runs.
- Insert a `detection_audits` row (`reason='initial_prediction'`,
  `to_class_id=matched_class | NULL`, `model_version_id=version.id`)
  and publish `frame.updated`.

### `vd.finetune_yolo(training_run_id: uuid)`
- The **API** creates the `training_runs` row (`status='queued'`) and enqueues
  the task; the task receives the run id. Triggered manually by the owner via
  `POST /training-runs { kind: 'yolo' }` (the `/training` page). YOLO
  fine-tunes are never enqueued automatically; the labeling write paths only
  auto-trigger per-class classifier retrains (see
  `services/training_service.py`).
- Steps:
  1. Mark the run `running`; resolve the active YOLO checkpoint as the base.
  2. Build the YOLO dataset (`worker/dataset.py`): every ground-truth
     detection (`source='user' OR reviewed`) across all classes — so COCO
     classes are not forgotten — on frames whose JPEG survives. Symlink the
     frame JPEGs; write `<idx> <xc> <yc> <w> <h>` labels; split 80/10/10 by
     frame; write `data.yaml`.
  3. Call `vd_ml.unload_inference_models()` to drop the resident YOLO,
     InsightFace, and DINOv2 caches and `torch.cuda.empty_cache()`. Without
     this, those three eat enough VRAM that YOLOv11-L at imgsz=960 batch=16
     OOMs and the cuDNN context dies with
     `CUDNN_STATUS_EXECUTION_FAILED_CUDART` after Ultralytics' auto-recovery.
     The next inference task transparently re-loads them via the `lru_cache`
     loaders.
  4. Train from the previous checkpoint via `vd_ml.train_yolo` in a worker
     thread; bridge per-epoch progress back as `training_run.update` events.
     `train_yolo` passes `workers=0` to Ultralytics: the Celery prefork worker
     is daemonic and cannot fork DataLoader child processes.
  5. Register a new `model_versions` row. **Regression guard:** activate it
     (via `vd_db.activate_model_version`) only if val mAP50-95 ≥ the previous
     active model's − 0.01 (skipped on the first-ever fine-tune). Activation
     deactivates the prior model and syncs `classes.yolo_class_index`.
  6. Mark the run `succeeded`/`failed`; broadcast `model.active_changed`.
- Training failures (OOM, bad data) are terminal — the run is marked `failed`
  and the task returns; no Celery retry.
- **Orphan sweep on worker boot** (`worker/orphans.py`): the `worker_ready`
  Celery signal — gated on the worker consuming the `train` queue — flips
  any `TrainingRun` left at `status='running'` to `failed` with
  `error='worker restarted before completion'`. Single-host single-worker
  means a `running` row that survives a worker restart is by definition
  stale; without the sweep, a crash mid-train (OOM, container restart,
  deploy) would show as phantom in-progress training forever. The cpu
  worker shares the same codebase but the handler no-ops there.

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

### `vd.dedup_clip_frames(clip_id: uuid)` *(`cpu` queue)*

Collapses runs of near-identical frames within one clip down to a single
representative. Scheduled by `vd.detect_frame_batch` once the clip finishes
detecting; a no-op when `prune_similar_frames` is unset.

- Load the clip's frames with `kept=true` and a non-null `phash`, ordered by
  `frame_index`. (Frames with no `phash` — e.g. pre-feature clips not yet
  backfilled — are skipped, never pruned.)
- Walk the sequence holding a *reference* frame. For each next frame, take the
  Hamming distance between its `phash` and the reference's:
  - **distance > `frame_similarity_threshold`** → the scene changed; this
    frame becomes the new reference. Keep it.
  - **distance ≤ threshold** → candidate duplicate of the reference. Confirm
    it is **detection-aware redundant**: same set of `class_id`s as the
    reference frame, with each box's centre within a small tolerance. Only
    then is it a true duplicate.
- For each confirmed duplicate frame:
  - **Skip it entirely if any of its detections is `reviewed=true` or
    `source='user'`** — reviewed/user boxes are ground truth and are never
    pruned. A frame carrying one keeps the whole frame.
  - Otherwise set `frames.kept=false`, soft-delete its detections
    (`deleted_at=now()`, plus a `user_delete` audit row with
    `model_version_id` carried over so the ledger stays complete), and
    schedule `vd.prune_frame(frame_id)` on `cpu` to unlink the JPEG. A deduped
    frame is redundant by definition, so its JPEG is always unlinked — the
    gate that authorised it is `prune_similar_frames`, checked once here, not
    per file. (Dedup is now the only writer of `kept=false`; empty-detection
    frames stay kept so the user can manually add boxes YOLO missed.)
- Representative choice: the reference is not blindly the first frame of a
  run — among a run of mutual duplicates, keep the frame with the most
  detections, tie-broken by highest mean `confidence_class`, so the surviving
  frame is the most informative one.
- Comparison is **within a clip only** and strictly between `frame_index`-
  adjacent frames, so a clip that revisits a scene is not over-collapsed.
- Publish `clip.frames.deduped` with the kept/pruned counts.

Idempotent: re-running only ever finds already-`kept=true` frames, and an
identical walk produces the same survivors.

Rationale for *detection-aware* (not pure pHash): a whole-frame perceptual
hash can read two frames as near-identical while one has gained a small but
real detection (someone entering at the frame edge). Requiring the detection
sets to also match means dedup never hides a frame where something changed —
the labeling queue shrinks without losing a single new object.

### `vd.backfill_frame_phash(clip_id?: uuid)` *(`cpu` queue)*

One-off migration for frames extracted before phash existed (all pre-feature
clips have `phash IS NULL`). For each `kept=true` frame with `path` set and
`phash IS NULL`: read the JPEG, compute the perceptual hash, write `phash`.
Then, if `prune_similar_frames` is set, chain into `vd.dedup_clip_frames` for
each affected clip so historical clips get the same treatment as new ones.

- Scoped to one clip when `clip_id` is given, else sweeps every clip.
- Idempotent and resumable — a frame that already has a `phash` is skipped, so
  a re-run only picks up what is still missing.
- Frames whose JPEG was already purged (`path IS NULL`, e.g. via
  `vd.purge_frames`) cannot be hashed and are left as-is.

### `vd.purge_frames(older_than_days: int)` *(Phase 7, `cpu` queue)*
- Disk reclamation: deletes the JPEG of every frame whose clip is older than
  the cutoff and nulls `frames.path`. Frame + detection rows (and the audit
  ledger) are kept — only the images go. Triggered by `POST /system/purge-frames`.

### `vd.reextract_frames(clip_id: uuid)` *(`cpu` queue)*

Drop a clip's frames + detections and run extraction again. Scheduled by
`POST /api/clips/{id}/reextract` (the clip detail page's "Re-extract frames"
button). The button is the recovery path when the original detection pass
ran with a worse model, with a wrong fps setting, or simply failed.

- Verify `clip.final_path` still exists; if not, set `clip.status='failed'`
  with an explanatory `error` and stop — wiping state we can't recover from
  would be destructive.
- `DELETE FROM frames WHERE clip_id = …` (Core delete so the
  `ondelete=CASCADE` FKs drop detections, audits, and any
  `subclass_examples` pointing at those detections). Clear
  `clip.processed_at` + `error`, set `status='extracting'`, reset
  `ingested_at` to now, commit.
- `shutil.rmtree(frames_dir)` to remove the frame JPEGs on disk.
- Schedule `vd.extract_frames(clip_id)` on `cpu`. The status flips to
  `detecting` once that runs, then `done` — the SSE event train is
  identical to a fresh ingest, so the UI doesn't need a re-extract-specific
  branch.

Idempotent: the DB delete + status reset commit before any file work, so a
crash leaves the clip in `extracting` with zero frames + zero detections,
and re-running converges cleanly. The crop thumbnails cache
(`<frames_dir>/.thumbs/<detection_id>_…`) is keyed by detection id and is
left as harmless orphans — the dropped detection ids never resolve again.

### `vd.delete_clip(clip_id: uuid)` *(Phase 7, `cpu` queue)*
- Removes a clip: deletes the frame directory, deletes the source video iff
  `delete_processed_videos`, then issues a Core `DELETE` so the
  `ondelete=CASCADE` FKs drop frames + detections. Publishes `clip.deleted`.
  Triggered by `DELETE /clips/{id}`. Idempotent — a missing clip is a no-op.

### `vd.deliver_callback(clip_id: uuid, event: str)` *(`cpu` queue)*

Delivers the job result of an externally-submitted clip back to its
`callback_url`. Scheduled when a clip with a `callback_url` reaches `done` /
`failed` (and for duplicate clips resolving through `canonical_clip_id`).
`event` is `clip.done` or `clip.failed`.

- No-op if the clip (resolved through `canonical_clip_id`) has no `callback_url`.
- Upsert the `webhook_deliveries` row keyed on `(clip_id, event)` (spec 03):
  snapshot `url`, build `payload` = the spec 04 §Jobs result body.
- POST `payload` to `url` with a `VD_WEBHOOK_TIMEOUT_SEC` timeout.
  - `2xx` → `status='delivered'`, record `response_status`.
  - otherwise → increment `attempts`, record `last_error` / `response_status`,
    and retry with exponential backoff + jitter up to `VD_WEBHOOK_MAX_ATTEMPTS`;
    after the last attempt `status='failed'` (terminal — left for manual
    inspection, no dead-letter routing).
- Idempotent: keyed on `webhook_deliveries.(clip_id, event)`; a `delivered` row
  is never re-sent. Retries are the Celery task re-running against that row.

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
    def on_closed(self, event):       # IN_CLOSE_WRITE — `cp`, direct write
        path = Path(event.src_path)
        if path.suffix.lower() in VIDEO_EXTS:
            celery_app.send_task("vd.ingest_video", args=[str(path)], queue="cpu")

    def on_moved(self, event):        # IN_MOVED_TO — atomic rename into inbox
        path = Path(event.dest_path)
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
- We also listen on `on_moved`: `POST /api/clips/upload` streams an upload to a
  hidden `.part` file (which `on_closed` ignores — non-video suffix), then
  atomically renames it to the final video name. A rename is `IN_MOVED_TO`, not
  a close, so it would be missed without `on_moved`. The renamed file is
  already complete, so reacting immediately is safe.
- If `on_closed` is not available on the host's filesystem (e.g., some FUSE
  mounts), fall back to a stable-size poll: schedule when size + mtime have
  been unchanged for ~3 seconds.
- The startup scan handles files that landed while the watcher was down.
- The watcher schedules only on `inbox_dir`. `intake_dir` — where external
  apps write videos before calling `POST /api/jobs` — is deliberately **not**
  watched, so the API call stays the sole trigger for app-submitted videos
  (spec 02 §External video submission).

## Idempotency & failure recovery

Each task is idempotent:
- `ingest_video`: SHA dedup. The source video is moved out of its source
  directory (`inbox/` for watcher drops, `intake/` for `POST /api/jobs`) as the
  task's *last* step — after the `clips` row is committed and `extract_frames`
  enqueued. A crash mid-task therefore leaves the file in place for a clean
  retry; once the file has moved, every prior step has succeeded, so a retry
  short-circuits on the not-in-source-dir check.
- `extract_frames`: upsert on `(clip_id, frame_index)`.
- `detect_frame_batch`: skip frames whose `detect_status='done'`. Clip
  completion is a single conditional `UPDATE clips SET status='done' WHERE
  status='detecting' AND NOT EXISTS (pending frames)` — the status guard plus
  `rowcount` make it correct even if batches for one clip run concurrently
  (a read-then-write check would double-fire `clip.done`).
- `recognize_face` / `embed_object`: skip if embedding already non-null.
- `assign_subclass`: pure compute; safe to re-run; only updates if the
  detection has not been user-reviewed.

Failure handling:
- Retry policy: `autoretry_for=(SomeTransientError,)`, max_retries=3,
  exponential backoff, jitter.
- Permanent failures move the clip to `failed/` and set `status='failed'`
  with the error message. Visible in the UI; user can fix and re-enqueue.
  *Implemented so far:* `ingest_video` quarantines the source video to
  `failed/` once retries are exhausted, so the inbox watcher stops looping on
  a bad file. Writing a `status='failed'` `clips` row for ingest failures
  (where no row may exist yet) is still deferred — see `deferred.md`.
- Dead-letter queue: failed tasks beyond max_retries are routed to a
  `dead` queue we can inspect via Flower.
- External jobs: whenever a clip reaches `failed` (or `done`) and has a
  `callback_url`, `vd.deliver_callback` is scheduled with the matching event so
  the submitting app is told the outcome — see `vd.deliver_callback` above.

## Configuration knobs (re-stated from spec 02)

- `VD_FRAME_FPS` — sample rate (default 1.0).
- `VD_DETECTION_MIN_CONFIDENCE` — discard threshold (default 0.25).
- `VD_SUBCLASS_MIN_CONFIDENCE` — sub-class cosine threshold (default 0.55).
- `VD_SUBCLASS_RETRAIN_THRESHOLD` — labels needed (default 25).
- `VD_DELETE_PROCESSED_VIDEOS` — bool (default false).
- `VD_COMPRESS_PROCESSED_VIDEOS` — bool (default true). When set, the extract
  task schedules `vd.compress_video` after the detect batches. Disable to
  keep the original codec/bitrate on disk.
- `VD_COMPRESS_CRF` — int (default 22). The constant-quality target passed
  to `hevc_nvenc` as `-cq` (NVENC's CRF analog; lower = larger + higher
  quality).
- `VD_PRUNE_SIMILAR_FRAMES` — bool (default true). Master switch for
  `vd.dedup_clip_frames`; when unset the task is a no-op.
- `VD_FRAME_SIMILARITY_THRESHOLD` — int (default 6). Max pHash Hamming
  distance (out of 64) at which two adjacent frames are duplicate candidates.
  Higher = more aggressive pruning.
- `VD_WEBHOOK_TIMEOUT_SEC` — float (default 10.0). Per-attempt timeout for the
  `vd.deliver_callback` POST.
- `VD_WEBHOOK_MAX_ATTEMPTS` — int (default 5). Callback retries before the
  `webhook_deliveries` row is marked `failed`.

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
- **GPU OOM safety net**: *implemented* — `vd_ml.yolo.predict_batch` catches
  CUDA `out of memory` errors, calls `torch.cuda.empty_cache()`, and recurses
  on each half of the batch; a single image that still OOMs re-raises. If
  this fires often, lower `VD_DETECT_BATCH_SIZE`.
- **Process restart cost**: loading YOLO+InsightFace+DINOv2 weights once
  costs ~5–10s. Celery worker `--max-tasks-per-child` should be disabled or
  set very high so we don't reload per task.

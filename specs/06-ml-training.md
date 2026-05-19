# 06 — ML & Training

This spec covers what runs on the GPU and how it gets smarter over time.

## Models

| Role               | Model                                       | Notes                              |
|--------------------|---------------------------------------------|------------------------------------|
| Object detection   | Ultralytics YOLOv11-L (`yolo11l.pt`)        | starting point; fine-tuned for custom classes |
| Face detection     | InsightFace `buffalo_l` (RetinaFace)        | bundled with the package           |
| Face embeddings    | InsightFace ArcFace ResNet50 (512-d)        | bundled with `buffalo_l`           |
| Generic embeddings | DINOv2 base (`facebook/dinov2-base`, 768-d)  | for non-face sub-class kNN       |
| Per-class subclass classifier | Logistic regression on embeddings | trained when threshold reached |

Why YOLOv11-L: best speed/accuracy trade-off for a single consumer GPU at
1 FPS sampling. Drop to `yolo11s` if VRAM is tight; bump to `yolo11x` if
accuracy needs it.

Why DINOv2 (not CLIP) for non-face crops: DINOv2 embeddings are stronger
for instance-level / fine-grained discrimination, which is what tells two
dogs apart. CLIP is better for free-text similarity but worse here.

Why `dinov2-base` (not `-small`): the `object_embedding` pgvector column is
`vector(768)`, and only the `base` checkpoint emits 768-d vectors —
`dinov2-small` is 384-d. `base` (~88M params) is still fast at 1 FPS sampling.

Why a calibrated linear classifier on top once labels exist: kNN works at
zero training cost but is noisy at the boundaries and slow at scale. A
small logistic regression on the same embeddings is faster, calibrated,
and trivially retrainable.

## Detection pipeline (model side of spec 05)

```
JPEG → preprocess (letterbox to 960) → YOLO predict (conf>=0.25, iou=0.45)
     → boxes + class indices + scores
     → for each box:
         lookup class_id from yolo_class_index
         insert detection (predicted = current = class_id)
```

The class index → class_id mapping is read from the `classes.yolo_class_index`
column. `vd_db.activate_model_version` keeps that column in sync: whenever a
YOLO model is activated it rewrites every `yolo_class_index` from the model's
recorded `metrics["class_names"]` (matching by name), clearing classes the
model does not know. Custom classes get an index after the first fine-tune;
rolling back to the COCO base restores the COCO indices.

## Sub-class assignment

Two regimes:

### Regime A — bootstrap (no per-class classifier yet)
- Person + face present: kNN over face embeddings of `subclass_examples`
  in that class. Top-5 nearest, majority vote; winning mean cosine sim ≥
  `subclass_min_confidence` → assign.
- Non-person classes: kNN over DINOv2 embeddings the same way.

### Regime B — per-class classifier exists
- Use the active classifier's softmax over the class's sub-classes.
- Top-1 prob ≥ `subclass_min_confidence` → assign.
- Confidence equals classifier max prob.

Switching regimes:
- A classifier is trained when a class has ≥ `subclass_retrain_threshold`
  labels across ≥ 2 sub-classes (otherwise it would collapse to one class).
- Once a classifier is `is_active=true`, Regime B is used.
- If the user marks the classifier inactive (UI), we fall back to Regime A.

### kNN implementation

In Postgres + pgvector:
```sql
SELECT se.subclass_id,
       1 - (d.face_embedding <=> $1) AS cosine_sim
FROM subclass_examples se
JOIN detections d ON d.id = se.detection_id
JOIN subclasses s ON s.id = se.subclass_id
WHERE s.class_id = $2 AND s.is_active
ORDER BY d.face_embedding <=> $1
LIMIT 5;
```

Take majority vote among the top 5; tie-break by mean cosine sim.

## Custom-class lifecycle (fine-tune)

```
[user] creates class "deer" (source=custom)
   ↓
[user] labels frames containing deer via the bbox UI
       (frames that may not have any current detections — they draw new boxes)
   ↓
[system] counts labeled deer detections (source='user' OR reviewed=true,
         class=deer). When count ≥ VD_CUSTOM_CLASS_FINETUNE_THRESHOLD,
         enqueue vd.finetune_yolo unless one is already running/queued.
   ↓
[worker] builds dataset including BOTH:
         - newly labeled deer detections
         - existing reviewed COCO-class detections (otherwise the fine-tune
           would catastrophically forget COCO classes)
   ↓
[worker] runs ultralytics training. Records mAP/precision/recall.
   ↓
[worker] writes model_versions row, activates if validation mAP ≥
         previous active mAP - 1pp (regression guard).
   ↓
[broadcast] new model available; UI shows banner + offers backfill.
```

Catastrophic forgetting guard:
- Always train from the previous active checkpoint, not from COCO-pretrained.
- The dataset includes every reviewed/user detection across all classes, so
  existing classes stay represented (no per-class oversampling yet).
- Regression guard (implemented): a new model is activated only if its
  aggregate val mAP50-95 ≥ the previous active model's − 0.01; otherwise the
  `model_versions` row is registered but left inactive. A *per-class* mAP
  regression check is a future enhancement.

Dataset layout (Ultralytics standard):
```
training/run_<id>/
├── data.yaml
├── images/
│   ├── train/
│   ├── val/
│   └── test/
└── labels/
    ├── train/
    ├── val/
    └── test/
```

For each frame contributing to the dataset, we write the full frame JPEG +
a labels txt with one line per detection: `<class_idx> <xc> <yc> <w> <h>`.

## Accuracy tracking

We promised "keep track of the accuracy of automatic assignments over time."
Definition:

For a `model_version` `M`:
- **Class accuracy (top-1)** = fraction of reviewed detections produced by
  `M` where `predicted_class_id == class_id` at review time.
- **Sub-class accuracy (top-1)** = same for `predicted_subclass_id`.
- **Per-class precision** = of detections predicted as class C by M,
  fraction whose reviewed class is C.
- **Per-class recall** = of reviewed detections that ARE class C, fraction
  M predicted as C.
- **Calibration**: bin predictions by `confidence_class` into deciles;
  empirical accuracy per bin → ECE = Σ |acc_bin - mean_conf_bin| · weight_bin.

The unit of measurement is the **reviewed** detection. Until the user
reviews, we don't know the truth. The `detection_audits` table is the
ledger: it records the model's initial prediction and every user state
change, with timestamps. Metrics are computed as a join over `audits` +
current `detections`.

### Time-series query (sketch)

```sql
WITH reviewed AS (
  SELECT d.id, d.class_id, d.predicted_class_id, d.reviewed_at, d.model_version_id
  FROM detections d
  WHERE d.reviewed
)
SELECT
  date_trunc('day', reviewed_at) AS day,
  model_version_id,
  COUNT(*) AS n,
  AVG((predicted_class_id = class_id)::int)::float AS class_top1
FROM reviewed
GROUP BY 1,2
ORDER BY 1;
```

This is exposed through `/api/metrics/accuracy?bucket=day`.

### Materialized view

**Status (Phase 6):** the `/api/metrics/*` endpoints compute these roll-ups
**on-the-fly** with GROUP BY queries — instant at single-user scale. The
`daily_metrics` materialized view + nightly Celery-beat refresh below is
**deferred** (see `specs/deferred.md`); adopt it only when the `detections`
table grows large enough that the live queries lag.

For larger datasets, materialize the daily roll-up:
```sql
CREATE MATERIALIZED VIEW daily_metrics AS
SELECT
  date_trunc('day', d.reviewed_at) AS day,
  d.class_id,
  d.model_version_id,
  COUNT(*) AS n_reviewed,
  AVG((d.predicted_class_id = d.class_id)::int) AS class_top1,
  AVG((d.predicted_subclass_id IS NOT DISTINCT FROM d.subclass_id)::int) AS subclass_top1,
  AVG(d.confidence_class) AS mean_confidence
FROM detections d
WHERE d.reviewed
GROUP BY 1, 2, 3;
```
Refresh nightly + on demand after retraining. Indexed on `(day, class_id,
model_version_id)`.

### Calibration

Surfaced in the UI as a reliability diagram. Computed from the same
`reviewed` set, bucketing on `confidence_class`.

If calibration is bad (ECE > 0.05), the UI flags it and suggests a
calibration retrain — fit a Platt scaling (or isotonic) wrapper on top of
the YOLO scores using the reviewed set, store as `model_versions` of
kind `classifier` with `target_class_id=NULL` and `name='yolo-cal-v1'`.
Application is a post-processing step in `detect_frame_batch`.

## Model registry behavior

- Only one `model_versions` row per `kind` (+ `target_class_id` for
  classifier kind) may have `is_active=true`. Enforced in-app by the single
  activation transaction in `vd_db.activate_model_version` (shared by the API
  and the worker) — not a DB constraint.
- No model-change pub/sub listener is needed: `detect_frame_batch` re-resolves
  the active `model_versions` row at the start of every batch, and `load_yolo`
  is an LRU cache keyed by weights path, so a newly activated model is picked
  up on the next batch (and rollback is instant — the old model stays cached).

## Performance targets (rough)

On a single RTX 4070 / 4080-class GPU:
- YOLOv11-L at 960px, batch=16: ~30–50 fps inference → can chew through
  a 1-hour video sampled at 1 FPS in well under a minute.
- InsightFace embedding: 5–10 ms/face.
- DINOv2-S embedding: 5–10 ms/crop.
- Throughput likely IO-bound, not GPU-bound, at this rate.

## Open questions

- **Imbalanced classes**: a custom class with 100 labels next to COCO
  classes with thousands of latent reviewed detections will be
  under-represented during fine-tune. Use weighted sampling in the
  dataset builder (oversample new classes).
- **Hard-negative mining**: for sub-class assignment, false-positive
  examples (incorrect kNN matches the user rejected) should also seed
  the classifier as negatives. Store rejection events in `detection_audits`
  and consume them at retrain time.
- **GPU eviction during training**: when `vd.finetune_yolo` runs, it can
  starve `vd.detect_frame_batch`. We could either (a) hard-pause inference
  during training (simple), or (b) share VRAM with cooperative scheduling
  (complex). Default to (a) for v1.

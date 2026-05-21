"""YOLOv11 object detection: weight management, model loading, batched inference.

This module is DB-free. The worker resolves the active `model_versions` row
and passes its `weights_path` here. Ultralytics is imported lazily so the pure
geometry helper (`to_normalized_bbox`) stays importable without the heavy dep.
"""

import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple


class Box(NamedTuple):
    """One detected box: COCO class index, score, normalized `{x,y,w,h}` bbox."""

    class_index: int
    score: float
    bbox: dict[str, float]


def to_normalized_bbox(
    x1: float, y1: float, x2: float, y2: float, img_w: float, img_h: float
) -> dict[str, float]:
    """Convert pixel xyxy corners to a normalized 0..1 `{x,y,w,h}` bbox.

    Corners are sorted and the result clamped so it always stays inside the
    frame — the DB `bbox_shape` check and the API `Bbox` schema both assume it.
    """
    lo_x, hi_x = sorted((x1, x2))
    lo_y, hi_y = sorted((y1, y2))
    nx = min(max(lo_x / img_w, 0.0), 1.0)
    ny = min(max(lo_y / img_h, 0.0), 1.0)
    nw = min(max((hi_x - lo_x) / img_w, 0.0), 1.0 - nx)
    nh = min(max((hi_y - lo_y) / img_h, 0.0), 1.0 - ny)
    return {"x": nx, "y": ny, "w": nw, "h": nh}


def iou(a: dict[str, float], b: dict[str, float]) -> float:
    """Intersection-over-union of two normalized `{x,y,w,h}` bboxes.

    Returns 0.0 for non-overlapping or degenerate boxes. Both inputs use the
    same `{x,y,w,h}` shape stored on `detections.bbox`.
    """
    ax1, ay1, ax2, ay2 = a["x"], a["y"], a["x"] + a["w"], a["y"] + a["h"]
    bx1, by1, bx2, by2 = b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union > 0.0 else 0.0


def ensure_base_weights(models_dir: Path, model_name: str = "yolo11l.pt") -> Path:
    """Return the path to the base YOLO weights, downloading them once if absent.

    Weights live under `<models_dir>/yolo/base/`. Ultralytics downloads bare
    model names next to the CWD, so we copy the result into place.
    """
    target = models_dir / "yolo" / "base" / model_name
    if target.exists():
        return target

    from ultralytics import YOLO

    target.parent.mkdir(parents=True, exist_ok=True)
    model = YOLO(model_name)  # triggers the GitHub asset download
    src = Path(getattr(model, "ckpt_path", "") or model_name)
    if src.exists() and src.resolve() != target.resolve():
        shutil.copy2(src, target)
    return target if target.exists() else src


@lru_cache(maxsize=4)
def load_yolo(weights_path: str) -> Any:
    """Load a YOLO model, cached per weights path (process-level singleton)."""
    from ultralytics import YOLO

    return YOLO(weights_path)


def _require_cuda_device(device: int | str) -> int | str:
    """Return `device`, raising if a CUDA device was requested but is absent.

    The `gpu` queue is sized around the single GPU. Ultralytics silently falls
    back to CPU when CUDA is missing — inference still "works" but at ~10× the
    latency, quietly starving the pipeline. We'd rather fail loudly: a missing
    GPU is a deployment fault, not something to paper over. Pass `device="cpu"`
    to opt out (tests, CPU-only contexts).
    """
    if device == "cpu":
        return device
    try:
        import torch

        cuda_available = torch.cuda.is_available()
    except ImportError:  # torch absent ⇒ definitely no GPU
        cuda_available = False
    if not cuda_available:
        raise RuntimeError(
            f"YOLO inference requested CUDA device {device!r} but no GPU is "
            "visible (torch missing or torch.cuda.is_available() is False) — "
            "the gpu worker has no usable GPU. Run `python -m worker.gpu_check` "
            'to diagnose, or pass device="cpu" to run on CPU intentionally.'
        )
    return device


def _predict_with_oom_retry(
    model: Any, image_paths: list[Path], conf: float, device: int | str
) -> list[Any]:
    """Run YOLO inference, halving the batch and retrying on CUDA OOM.

    A long-lived GPU worker can't afford to fail a whole clip because one
    oversized batch exhausted VRAM. On `out of memory` we free the cache and
    recurse on each half; a single image that still OOMs re-raises so the
    caller's retry/alerting can take over.
    """
    if not image_paths:
        return []
    try:
        return list(
            model.predict(
                source=[str(p) for p in image_paths],
                conf=conf,
                device=device,
                verbose=False,
            )
        )
    except RuntimeError as exc:  # torch.cuda.OutOfMemoryError subclasses this
        if "out of memory" not in str(exc).lower() or len(image_paths) == 1:
            raise
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        mid = len(image_paths) // 2
        return _predict_with_oom_retry(model, image_paths[:mid], conf, device) + (
            _predict_with_oom_retry(model, image_paths[mid:], conf, device)
        )


def predict_batch(
    model: Any, image_paths: list[Path], conf: float, device: int | str = 0
) -> list[list[Box]]:
    """Run YOLO on a batch of image files; return per-image lists of `Box`.

    The output list is aligned with `image_paths`. Degenerate (zero-area)
    boxes are dropped. `device` is pinned to CUDA 0 by default and a missing
    GPU raises rather than silently falling back to CPU — see
    `_require_cuda_device`.
    """
    results = _predict_with_oom_retry(
        model, image_paths, conf, _require_cuda_device(device)
    )
    batch: list[list[Box]] = []
    for res in results:
        boxes: list[Box] = []
        if res.boxes is not None and len(res.boxes) > 0:
            img_h, img_w = res.orig_shape
            for cls, score, xyxy in zip(
                res.boxes.cls.tolist(),
                res.boxes.conf.tolist(),
                res.boxes.xyxy.tolist(),
                strict=True,
            ):
                bbox = to_normalized_bbox(*xyxy, img_w, img_h)
                if bbox["w"] <= 0.0 or bbox["h"] <= 0.0:
                    continue
                boxes.append(Box(class_index=int(cls), score=float(score), bbox=bbox))
        batch.append(boxes)
    return batch

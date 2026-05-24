"""YOLO fine-tuning — a thin wrapper around Ultralytics `model.train()`.

DB-free, mirroring `vd_ml.yolo`. The worker assembles the dataset directory and
passes paths here; Ultralytics is imported lazily so the module stays light.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

EpochCallback = Callable[[int, int, dict[str, float]], None]


class YoloTrainResult(NamedTuple):
    """Outcome of one fine-tune run."""

    best_weights: str
    map50_95: float
    map50: float
    precision: float
    recall: float
    epochs: int
    # Per-class validation metrics keyed by class name. Empty if Ultralytics did
    # not surface them (e.g. a val split with zero labels for every class).
    per_class_map50_95: dict[str, float]
    per_class_map50: dict[str, float]


def train_yolo(
    base_weights: str,
    data_yaml: str,
    run_name: str,
    project_dir: str,
    epochs: int = 50,
    imgsz: int = 960,
    device: int | str = 0,
    on_epoch_end: EpochCallback | None = None,
) -> YoloTrainResult:
    """Fine-tune YOLO from `base_weights` on the dataset described by `data_yaml`.

    Blocking and GPU-bound — the caller runs this in a worker thread. When
    `on_epoch_end` is given it is invoked from Ultralytics' training thread
    after each epoch with `(epoch, total_epochs, metrics)`; the callback must be
    thread-safe (the worker bridges it back onto its event loop).
    """
    from ultralytics import YOLO

    model = YOLO(base_weights)

    if on_epoch_end is not None:
        callback = on_epoch_end

        def _on_epoch(trainer: Any) -> None:
            epoch = int(getattr(trainer, "epoch", 0)) + 1
            total = int(getattr(trainer, "epochs", epochs))
            raw = getattr(trainer, "metrics", None) or {}
            metrics = {str(k): float(v) for k, v in raw.items()}
            callback(epoch, total, metrics)

        model.add_callback("on_train_epoch_end", _on_epoch)

    results = model.train(
        data=data_yaml,
        epochs=epochs,
        imgsz=imgsz,
        device=device,
        project=project_dir,
        name=run_name,
        exist_ok=True,
        verbose=False,
        # The caller is a Celery prefork worker, whose processes are daemonic
        # and so cannot spawn children. workers>0 would have the DataLoader
        # fork worker processes and crash; load in-process instead.
        workers=0,
    )
    summary: dict[str, float] = dict(getattr(results, "results_dict", {}) or {})
    best = Path(results.save_dir) / "weights" / "best.pt"
    return YoloTrainResult(
        best_weights=str(best),
        map50_95=summary.get("metrics/mAP50-95(B)", 0.0),
        map50=summary.get("metrics/mAP50(B)", 0.0),
        precision=summary.get("metrics/precision(B)", 0.0),
        recall=summary.get("metrics/recall(B)", 0.0),
        epochs=epochs,
        per_class_map50_95=_per_class(results, "maps"),
        per_class_map50=_per_class(results, "ap50"),
    )


def _per_class(results: Any, attr: str) -> dict[str, float]:
    """Pluck a per-class metric array off the Ultralytics result.

    Ultralytics exposes per-class metrics on `results.box` as a numpy array
    indexed by class id, paired with `results.names: dict[int, str]`. Both
    pieces are best-effort: if the model only saw one class or the val split
    starved one out, the array can be empty or the class can be missing — so
    we silently return what we can map.
    """
    box = getattr(results, "box", None)
    arr = getattr(box, attr, None)
    names = getattr(results, "names", None) or {}
    if arr is None or not names:
        return {}
    out: dict[str, float] = {}
    for idx, name in names.items():
        try:
            out[str(name)] = float(arr[int(idx)])
        except (IndexError, TypeError, ValueError):
            continue
    return out

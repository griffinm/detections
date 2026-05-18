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
    )

"""Free GPU memory held by the long-lived inference models.

The GPU worker is one process that keeps YOLO + InsightFace + DINOv2
resident across tasks — restarting them costs ~5–10 s and the worker can't
afford that per request. But that constantly-resident footprint leaves no
headroom for YOLO fine-tuning at the project's default imgsz/batch on a
16 GB GPU: Ultralytics OOMs at batch=16, auto-recovers, and the surviving
cuDNN state then dies with `CUDNN_STATUS_EXECUTION_FAILED_CUDART`.

The fine-tune task calls `unload_inference_models()` first to wipe those
three from VRAM. After training, the next inference task transparently
re-loads them (`lru_cache` repopulates on demand).
"""

from __future__ import annotations

import gc
import logging

from vd_ml.embeddings import load_dino
from vd_ml.faces import load_face_app
from vd_ml.yolo import load_yolo

logger = logging.getLogger(__name__)


def unload_inference_models() -> None:
    """Drop YOLO / InsightFace / DINOv2 caches and free CUDA memory.

    Safe to call when none are loaded: clearing an empty `lru_cache` is a
    no-op and `torch.cuda.empty_cache()` is harmless without an active CUDA
    context. Importing torch lazily keeps this module light for CPU-only
    callers.
    """
    load_yolo.cache_clear()
    load_face_app.cache_clear()
    load_dino.cache_clear()
    gc.collect()

    try:
        import torch
    except ImportError:
        return
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()
        free, total = torch.cuda.mem_get_info()
        logger.info(
            "unload_inference_models: %.1f / %.1f MiB free after unload",
            free / 1024 / 1024,
            total / 1024 / 1024,
        )

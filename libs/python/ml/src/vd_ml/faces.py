"""InsightFace face detection + ArcFace embedding (the `buffalo_l` pack).

DB-free, mirroring `vd_ml.yolo`: the worker passes the model-cache directory
and image crops; this module loads the model lazily (heavy dep) and returns
plain float lists ready for a pgvector column.
"""

from functools import lru_cache
from typing import Any

FACE_EMBEDDING_DIM = 512


@lru_cache(maxsize=2)
def load_face_app(pack_name: str = "buffalo_l", root: str | None = None) -> Any:
    """Load an InsightFace `FaceAnalysis` app, cached per (pack, root).

    `root` is the directory the pack is downloaded into — InsightFace creates
    `<root>/models/<pack_name>/`. `ctx_id=0` selects the first CUDA device and
    falls back to CPU automatically when no GPU is visible.
    """
    from insightface.app import FaceAnalysis

    app = FaceAnalysis(
        name=pack_name,
        root=root or "~/.insightface",
        allowed_modules=["detection", "recognition"],
    )
    app.prepare(ctx_id=0, det_size=(640, 640))
    return app


def detect_and_embed(app: Any, image_bgr: Any) -> list[float] | None:
    """Return the ArcFace embedding of the largest face in `image_bgr`.

    `image_bgr` is an OpenCV-convention BGR uint8 array — a person crop is
    fine, RetinaFace finds the face within it. Returns `None` when no face is
    detected. The embedding is L2-normalized (512-d), ready for cosine kNN.
    """
    faces = app.get(image_bgr)
    if not faces:
        return None
    largest = max(
        faces,
        key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
    )
    return [float(v) for v in largest.normed_embedding]

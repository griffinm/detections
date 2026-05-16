"""Load a frame JPEG and crop a detection's bbox region for embedding."""

from pathlib import Path
from typing import Any

from vd_db.models import DetectionModel, Frame


def crop_detection(frames_dir: Path, frame: Frame, detection: DetectionModel) -> Any | None:
    """Return the detection's bbox region of its frame as an RGB PIL image.

    The stored bbox is normalized `{x,y,w,h}`; it is converted to pixel
    corners and clamped to the image here. Returns `None` when the frame file
    is missing (pruned) or the bbox maps to a degenerate (<2 px) region.
    """
    from PIL import Image

    if frame.path is None:
        return None
    path = frames_dir / frame.path
    if not path.exists():
        return None

    img = Image.open(path).convert("RGB")
    width, height = img.size
    bbox = detection.bbox
    x1 = int(bbox["x"] * width)
    y1 = int(bbox["y"] * height)
    x2 = int((bbox["x"] + bbox["w"]) * width)
    y2 = int((bbox["y"] + bbox["h"]) * height)
    x1, x2 = max(0, min(x1, x2)), min(width, max(x1, x2))
    y1, y2 = max(0, min(y1, y2)), min(height, max(y1, y2))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    return img.crop((x1, y1, x2, y2))

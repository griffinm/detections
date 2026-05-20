"""On-disk-cached JPEG crops of detection bboxes.

The class detail gallery renders 200–400 detection tiles; loading the full
frame JPEG for each (1–2 MB) and CSS-cropping is what made the page sluggish.
Each tile instead points at `/api/detections/{id}/crop`, which materialises a
small JPEG of just that bbox to disk and serves it from there. Subsequent
hits skip Pillow entirely.

Cache key includes a short hash of the bbox so an edited bbox (rare — only
the labeling UI can resize) yields a different filename and the old crop
becomes a harmless orphan.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from vd_settings import Settings

_settings = Settings()
# Live alongside the frames so the cache survives container rebuilds (the
# frames volume is the one host mount that persists). Dot-prefixed so it
# doesn't appear in any clip-frame listing.
_CROPS_DIR = _settings.frames_dir / ".thumbs"


def _bbox_hash(bbox: dict[str, float]) -> str:
    key = f"{bbox['x']:.5f},{bbox['y']:.5f},{bbox['w']:.5f},{bbox['h']:.5f}"
    return hashlib.blake2b(key.encode(), digest_size=4).hexdigest()


def crop_url(detection_id: str, size: int = 192) -> str:
    return f"/api/detections/{detection_id}/crop?size={size}"


def cache_path(detection_id: str, bbox: dict[str, float], size: int) -> Path:
    return _CROPS_DIR / f"{detection_id}_{_bbox_hash(bbox)}_{size}.jpg"


def ensure_crop(
    detection_id: str,
    frame_path: str,
    bbox: dict[str, float],
    size: int,
) -> Path | None:
    """Return the cached crop path, generating it if needed.

    `frame_path` is relative to `settings.frames_dir`. Returns `None` if the
    source frame is missing on disk or the bbox is degenerate.
    """
    out = cache_path(detection_id, bbox, size)
    if out.exists():
        return out

    src = _settings.frames_dir / frame_path
    if not src.exists():
        return None

    from PIL import Image

    with Image.open(src) as img:
        rgb: Any = img.convert("RGB")
        w, h = rgb.size
        x1 = int(bbox["x"] * w)
        y1 = int(bbox["y"] * h)
        x2 = int((bbox["x"] + bbox["w"]) * w)
        y2 = int((bbox["y"] + bbox["h"]) * h)
        x1, x2 = max(0, min(x1, x2)), min(w, max(x1, x2))
        y1, y2 = max(0, min(y1, y2)), min(h, max(y1, y2))
        if x2 - x1 < 2 or y2 - y1 < 2:
            return None
        crop = rgb.crop((x1, y1, x2, y2))
        # Longest side -> `size`; preserve aspect so faces stay readable.
        crop.thumbnail((size, size), Image.Resampling.LANCZOS)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".jpg.tmp")
        crop.save(tmp, "JPEG", quality=82, optimize=True)
        tmp.replace(out)
    return out

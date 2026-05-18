"""Perceptual-hash helpers for near-duplicate frame pruning.

A frame's `phash` is a 64-bit DCT perceptual hash packed into 8 bytes and
stored in `frames.phash`. `vd.dedup_clip_frames` compares adjacent frames by
the Hamming distance between these hashes.
"""

from pathlib import Path


def compute_phash(path: Path) -> bytes:
    """64-bit pHash of an image, packed little-to-8-bytes for `frames.phash`.

    `imagehash`/`PIL`/`numpy` are imported lazily: this module is pulled in by
    the task autodiscovery on every worker, but only the `cpu`-queue worker
    that runs extraction actually needs the image stack.
    """
    import imagehash
    import numpy as np
    from PIL import Image

    with Image.open(path) as img:
        # hash_size=8 → an 8x8 boolean array, i.e. 64 bits.
        bits = imagehash.phash(img).hash
    return np.packbits(bits).tobytes()


def hamming(a: bytes, b: bytes) -> int:
    """Bit-difference count between two packed pHashes (0 = identical)."""
    return (int.from_bytes(a, "big") ^ int.from_bytes(b, "big")).bit_count()

"""DINOv2 generic image embeddings for non-face sub-class kNN.

`facebook/dinov2-base` is used (not `-small`): it emits 768-d vectors, the
width of the `detections.object_embedding` pgvector column. DINOv2 beats CLIP
for instance-level discrimination — telling two dogs apart. DB-free, mirroring
`vd_ml.yolo`.
"""

from functools import lru_cache
from typing import Any, NamedTuple

OBJECT_EMBEDDING_DIM = 768
DINO_MODEL = "facebook/dinov2-base"


class Dino(NamedTuple):
    """A loaded DINOv2 model bundle: image processor, model, torch device."""

    processor: Any
    model: Any
    device: str


@lru_cache(maxsize=1)
def load_dino(model_name: str = DINO_MODEL, cache_dir: str | None = None) -> Dino:
    """Load DINOv2 (processor + model), cached process-wide.

    Weights are pulled from the Hugging Face hub into `cache_dir`; set
    `HF_HOME` on the worker so they persist on the models volume between
    container restarts.
    """
    import torch
    from transformers import AutoImageProcessor, AutoModel

    processor = AutoImageProcessor.from_pretrained(model_name, cache_dir=cache_dir)
    model = AutoModel.from_pretrained(model_name, cache_dir=cache_dir)
    model.eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    return Dino(processor=processor, model=model, device=device)


def embed_crop(dino: Dino, image_rgb: Any) -> list[float]:
    """Embed one RGB image crop into an L2-normalized 768-d vector.

    `image_rgb` is a PIL image or HxWx3 RGB array; the processor handles
    resizing and normalization. The CLS-token `pooler_output` is used.
    """
    import torch

    inputs = dino.processor(images=image_rgb, return_tensors="pt").to(dino.device)
    with torch.no_grad():
        output = dino.model(**inputs)
    vec = output.pooler_output[0]
    vec = vec / vec.norm()
    return [float(v) for v in vec.cpu()]

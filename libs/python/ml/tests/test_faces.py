"""Unit tests for the InsightFace / DINOv2 embedding wrappers.

`detect_and_embed` takes the loaded app as an argument, so the largest-face
selection and embedding extraction are testable with a fake app — no
InsightFace, ONNX, or GPU needed.
"""

from vd_ml import FACE_EMBEDDING_DIM, detect_and_embed
from vd_ml.embeddings import DINO_MODEL, OBJECT_EMBEDDING_DIM


def test_embedding_dims_match_db_columns() -> None:
    assert FACE_EMBEDDING_DIM == 512
    assert OBJECT_EMBEDDING_DIM == 768
    # 768-d requires dinov2-base; dinov2-small would only be 384-d.
    assert DINO_MODEL == "facebook/dinov2-base"


class _FakeFace:
    def __init__(self, bbox: list[float], embedding: list[float]) -> None:
        self.bbox = bbox
        self.normed_embedding = embedding


class _FakeApp:
    def __init__(self, faces: list[_FakeFace]) -> None:
        self._faces = faces

    def get(self, image: object) -> list[_FakeFace]:
        return self._faces


def test_detect_and_embed_picks_largest_face() -> None:
    small = _FakeFace([0, 0, 10, 10], [0.1] * FACE_EMBEDDING_DIM)
    large = _FakeFace([0, 0, 100, 100], [0.9] * FACE_EMBEDDING_DIM)
    out = detect_and_embed(_FakeApp([small, large]), object())
    assert out == [0.9] * FACE_EMBEDDING_DIM


def test_detect_and_embed_returns_none_without_a_face() -> None:
    assert detect_and_embed(_FakeApp([]), object()) is None

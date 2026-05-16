"""Unit tests for the YOLO geometry + batch-inference helpers.

These exercise `vd_ml.yolo` without importing ultralytics — `load_yolo` and
`ensure_base_weights` import it lazily, so the pure helpers stay testable.
"""

from pathlib import Path

from vd_ml import Box, predict_batch, to_normalized_bbox


def test_to_normalized_bbox_basic() -> None:
    bbox = to_normalized_bbox(100, 50, 300, 250, img_w=400, img_h=500)
    assert bbox == {"x": 0.25, "y": 0.1, "w": 0.5, "h": 0.4}


def test_to_normalized_bbox_clamps_out_of_frame() -> None:
    bbox = to_normalized_bbox(-20, -10, 500, 600, img_w=400, img_h=500)
    assert bbox["x"] == 0.0
    assert bbox["y"] == 0.0
    assert bbox["x"] + bbox["w"] <= 1.0
    assert bbox["y"] + bbox["h"] <= 1.0


def test_to_normalized_bbox_sorts_corners() -> None:
    swapped = to_normalized_bbox(300, 250, 100, 50, img_w=400, img_h=500)
    ordered = to_normalized_bbox(100, 50, 300, 250, img_w=400, img_h=500)
    assert swapped == ordered


class _FakeTensor:
    def __init__(self, data: list[object]) -> None:
        self._data = data

    def tolist(self) -> list[object]:
        return self._data


class _FakeBoxes:
    def __init__(
        self, cls: list[float], conf: list[float], xyxy: list[list[float]]
    ) -> None:
        self.cls = _FakeTensor(cls)  # type: ignore[arg-type]
        self.conf = _FakeTensor(conf)  # type: ignore[arg-type]
        self.xyxy = _FakeTensor(xyxy)  # type: ignore[arg-type]
        self._n = len(cls)

    def __len__(self) -> int:
        return self._n


class _FakeResult:
    def __init__(self, boxes: object, orig_shape: tuple[int, int]) -> None:
        self.boxes = boxes
        self.orig_shape = orig_shape


class _FakeModel:
    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = results

    def predict(self, source: object, conf: float, verbose: bool) -> list[_FakeResult]:
        return self._results


def test_predict_batch_extracts_boxes_and_drops_degenerate() -> None:
    results = [
        _FakeResult(
            _FakeBoxes(
                cls=[0.0, 16.0],
                conf=[0.9, 0.8],
                # second box is zero-area and must be dropped
                xyxy=[[10, 10, 110, 210], [50, 50, 50, 50]],
            ),
            orig_shape=(400, 200),  # (height, width)
        ),
        _FakeResult(None, orig_shape=(400, 200)),
    ]
    # Two paths to match the two fake results (the model ignores `source`).
    batch = predict_batch(
        _FakeModel(results), [Path("a.jpg"), Path("b.jpg")], conf=0.25
    )

    assert len(batch) == 2
    assert batch[0] == [Box(class_index=0, score=0.9, bbox={"x": 0.05, "y": 0.025, "w": 0.5, "h": 0.5})]
    assert batch[1] == []


class _OomModel:
    """Raises a CUDA-OOM RuntimeError until the batch is split down to one image."""

    def __init__(self, max_batch: int) -> None:
        self._max_batch = max_batch

    def predict(
        self, source: list[str], conf: float, verbose: bool
    ) -> list[_FakeResult]:
        if len(source) > self._max_batch:
            raise RuntimeError("CUDA error: out of memory")
        return [_FakeResult(None, orig_shape=(100, 100)) for _ in source]


def test_predict_batch_splits_on_cuda_oom() -> None:
    # Batch of 4 OOMs until halved to 1; output stays aligned with the input.
    batch = predict_batch(
        _OomModel(max_batch=1), [Path(f"{i}.jpg") for i in range(4)], conf=0.25
    )
    assert batch == [[], [], [], []]

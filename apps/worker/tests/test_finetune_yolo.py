"""Integration test for `vd.finetune_yolo` with the Ultralytics call faked.

The dataset build, `model_versions` registration, the regression guard and the
`classes.yolo_class_index` sync all run for real against the test database.
"""

import uuid

import pytest
import vd_ml
from sqlalchemy import select
from vd_ml.training import YoloTrainResult

from vd_db.models import Class, Clip, DetectionModel, Frame, ModelVersion, TrainingRun
from worker.tasks import finetune_yolo as ft_mod
from worker.tasks.finetune_yolo import _evaluate_regression, _finetune_yolo_async


def _train_result(
    project: str,
    run_name: str,
    epochs: int,
    *,
    map50_95: float = 0.5,
    per_class: dict[str, float] | None = None,
) -> YoloTrainResult:
    return YoloTrainResult(
        best_weights=f"{project}/{run_name}/weights/best.pt",
        map50_95=map50_95,
        map50=0.7,
        precision=0.8,
        recall=0.6,
        epochs=epochs,
        per_class_map50_95=dict(per_class or {}),
        per_class_map50=dict(per_class or {}),
    )


@pytest.fixture(autouse=True)
def _fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(ft_mod, "publish", _noop)

    def fake_train(base, data_yaml, run_name, project, epochs, imgsz, device, on_epoch_end):  # type: ignore[no-untyped-def]
        on_epoch_end(1, epochs, {"metrics/mAP50-95(B)": 0.5})
        return _train_result(project, run_name, epochs)

    monkeypatch.setattr(vd_ml, "train_yolo", fake_train)


async def _seed_base_model(session) -> None:  # type: ignore[no-untyped-def]
    """An active base model so `get_or_register_yolo` never downloads weights."""
    session.add(
        ModelVersion(
            kind="yolo", name="base", weights_path="/models/base.pt",
            metrics={"class_names": {"0": "person"}, "source": "coco-pretrained"},
            is_active=True,
        )
    )


async def _seed_labels(session, frames_dir, n) -> None:  # type: ignore[no-untyped-def]
    clip = Clip(
        filename="t.mp4", original_path="/in/t.mp4",
        sha256=uuid.uuid4().hex, size_bytes=1, status="done",
    )
    session.add(clip)
    await session.flush()
    person = await session.scalar(select(Class.id).where(Class.name == "person"))
    for i in range(n):
        frame = Frame(
            clip_id=clip.id, frame_index=i, timestamp_sec=float(i),
            path=f"{clip.id}/f{i}.jpg", width=640, height=480,
            kept=True, detect_status="done",
        )
        session.add(frame)
        await session.flush()
        session.add(
            DetectionModel(
                frame_id=frame.id, class_id=person, predicted_class_id=person,
                bbox={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
                source="model", reviewed=True, confidence_class=0.9,
            )
        )
        path = frames_dir / frame.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xd8\xff")


async def test_finetune_registers_activates_and_syncs_indices(session, frames_dir):  # type: ignore[no-untyped-def]
    await _seed_base_model(session)
    await _seed_labels(session, frames_dir, n=12)
    run = TrainingRun(kind="yolo", status="queued")
    session.add(run)
    await session.commit()

    result = await _finetune_yolo_async(str(run.id))
    assert result not in ("failed", "missing")

    await session.refresh(run)
    assert run.status == "succeeded"

    versions = (
        await session.scalars(select(ModelVersion).where(ModelVersion.kind == "yolo"))
    ).all()
    assert len(versions) == 2
    new = next(v for v in versions if v.name != "base")
    base = next(v for v in versions if v.name == "base")
    assert new.is_active is True and base.is_active is False
    assert new.metrics["val_map50_95"] == 0.5

    # The base model had no recorded mAP -> regression guard skipped -> activated,
    # and classes.yolo_class_index now round-trips through the new model's
    # class-name list (the exact index depends on class enumeration order).
    person = await session.scalar(select(Class).where(Class.name == "person"))
    assert person.yolo_class_index is not None
    assert new.metrics["class_names"][str(person.yolo_class_index)] == "person"


def test_evaluate_regression_no_prev_activates() -> None:
    """First fine-tune (no prior metrics) always activates."""
    result = _evaluate_regression(
        prev_metrics=None,
        new_map50_95=0.5,
        new_per_class={"person": 0.6},
        new_val_counts={"person": 50},
        aggregate_tol=0.01,
        per_class_tol=0.05,
        min_val_samples=10,
    )
    assert result["activate"] is True
    assert result["aggregate"]["pass"] is True


def test_evaluate_regression_aggregate_block() -> None:
    result = _evaluate_regression(
        prev_metrics={"val_map50_95": 0.9},
        new_map50_95=0.5,
        new_per_class={},
        new_val_counts={},
        aggregate_tol=0.01,
        per_class_tol=0.05,
        min_val_samples=10,
    )
    assert result["activate"] is False
    assert result["aggregate"]["pass"] is False


def test_evaluate_regression_per_class_block() -> None:
    """Aggregate fine, but person regresses materially and is well-represented → block."""
    result = _evaluate_regression(
        prev_metrics={
            "val_map50_95": 0.80,
            "per_class_map50_95": {"person": 0.90, "car": 0.80},
            "per_class_val_samples": {"person": 50, "car": 50},
        },
        new_map50_95=0.80,
        new_per_class={"person": 0.70, "car": 0.82},
        new_val_counts={"person": 50, "car": 50},
        aggregate_tol=0.01,
        per_class_tol=0.05,
        min_val_samples=10,
    )
    assert result["activate"] is False
    assert result["blocked_classes"] == ["person"]
    entries = {e["class"]: e for e in result["per_class"]}
    assert entries["person"]["status"] == "fail"
    assert entries["car"]["status"] == "pass"


def test_evaluate_regression_skips_sparse_class() -> None:
    """A class with too few val samples is skipped, even if it 'regresses'."""
    result = _evaluate_regression(
        prev_metrics={
            "val_map50_95": 0.80,
            "per_class_map50_95": {"person": 0.90, "deer": 0.70},
            "per_class_val_samples": {"person": 50, "deer": 3},
        },
        new_map50_95=0.79,
        new_per_class={"person": 0.89, "deer": 0.20},
        new_val_counts={"person": 50, "deer": 4},
        aggregate_tol=0.01,
        per_class_tol=0.05,
        min_val_samples=10,
    )
    assert result["activate"] is True, result
    deer = next(e for e in result["per_class"] if e["class"] == "deer")
    assert deer["status"] == "skipped"


def test_evaluate_regression_new_class_does_not_block() -> None:
    """A class only present in the new model can't be gated on (no prev to compare)."""
    result = _evaluate_regression(
        prev_metrics={
            "val_map50_95": 0.80,
            "per_class_map50_95": {"person": 0.90},
            "per_class_val_samples": {"person": 50},
        },
        new_map50_95=0.80,
        new_per_class={"person": 0.89, "dog": 0.40},
        new_val_counts={"person": 50, "dog": 30},
        aggregate_tol=0.01,
        per_class_tol=0.05,
        min_val_samples=10,
    )
    assert result["activate"] is True
    dog = next(e for e in result["per_class"] if e["class"] == "dog")
    assert dog["status"] == "skipped"


def test_evaluate_regression_within_tolerance_passes() -> None:
    """A small per-class drop within tolerance is fine."""
    result = _evaluate_regression(
        prev_metrics={
            "val_map50_95": 0.80,
            "per_class_map50_95": {"person": 0.90},
            "per_class_val_samples": {"person": 50},
        },
        new_map50_95=0.79,
        new_per_class={"person": 0.87},
        new_val_counts={"person": 50},
        aggregate_tol=0.01,
        per_class_tol=0.05,
        min_val_samples=10,
    )
    assert result["activate"] is True


async def test_finetune_fails_when_no_labels(session, frames_dir):  # type: ignore[no-untyped-def]
    await _seed_base_model(session)
    run = TrainingRun(kind="yolo", status="queued")
    session.add(run)
    await session.commit()

    result = await _finetune_yolo_async(str(run.id))
    assert result == "failed"
    await session.refresh(run)
    assert run.status == "failed"
    assert run.error

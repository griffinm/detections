"""Unit tests for `vd_db.model_paths` — the relative-path round trip that keeps
the model registry independent of where `models_dir` is mounted."""

from pathlib import Path

from vd_db import resolve_model_path, to_stored_path

MODELS_DIR = Path("/data/models")


def test_path_under_models_dir_is_stored_relative():
    abs_path = MODELS_DIR / "yolo/runs/run_abc/weights/best.pt"
    stored = to_stored_path(MODELS_DIR, abs_path)
    assert stored == "yolo/runs/run_abc/weights/best.pt"
    assert resolve_model_path(MODELS_DIR, stored) == abs_path


def test_relative_resolves_against_a_moved_mount():
    stored = to_stored_path(MODELS_DIR, MODELS_DIR / "classifiers/c/v.joblib")
    # The same registry row resolves correctly under a different mount point —
    # the failure mode this module exists to prevent.
    moved = Path("/mnt/nas/app-data/video-detections/data/models")
    assert resolve_model_path(moved, stored) == moved / "classifiers/c/v.joblib"


def test_path_outside_models_dir_is_kept_absolute():
    outside = "/opt/some/other/place/best.pt"
    assert to_stored_path(MODELS_DIR, outside) == outside
    # Already-absolute (legacy rows / external paths) resolve to themselves.
    assert resolve_model_path(MODELS_DIR, outside) == Path(outside)

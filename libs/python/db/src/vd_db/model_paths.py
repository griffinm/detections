"""Model-weights paths in `model_versions.weights_path` (and `training_runs.
log_path`) are stored *relative to* `settings.models_dir`.

The models directory is a bind mount, and its host path has already moved once
(local disk → NAS). An absolute path captured at training time strands the
active model the instant the mount point changes — the worker dutifully tries
to load a path that no longer exists inside the container, retries, and the
clip wedges. Storing the path relative to `models_dir` makes the registry
independent of where the volume happens to be mounted; the absolute path is
reconstructed against the *current* `models_dir` at load time.
"""

from pathlib import Path


def to_stored_path(models_dir: Path, path: str | Path) -> str:
    """Path to persist — relative to `models_dir` when the file lives under it
    (the normal case for trained/registered weights), else the absolute string
    unchanged (paths outside the models dir have nothing to anchor to)."""
    p = Path(path)
    try:
        return str(p.relative_to(models_dir))
    except ValueError:
        return str(p)


def resolve_model_path(models_dir: Path, stored: str | Path) -> Path:
    """Inverse of `to_stored_path`: resolve a stored path to an absolute path
    under the current `models_dir`. Already-absolute values — paths outside the
    models dir, or rows written before relative storage — are returned as-is."""
    p = Path(stored)
    return p if p.is_absolute() else models_dir / p

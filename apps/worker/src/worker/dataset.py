"""Build an Ultralytics YOLO dataset directory from reviewed/user detections.

DB-aware (it reads detections + frame paths) but torch-free — it produces a
plain directory that `vd_ml.train_yolo` consumes. The dataset is every
ground-truth detection (user-drawn or reviewed) across all active classes, on
frames whose JPEG still exists on disk.
"""

import os
import random
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vd_db.models import Class, DetectionModel, Frame
from vd_settings import Settings

_SPLITS = ("train", "val", "test")


@dataclass
class YoloDatasetManifest:
    """The result of `build_yolo_dataset` — paths plus the class index list."""

    root: Path
    data_yaml: Path
    class_names: list[str]
    class_ids: list[uuid.UUID]
    counts: dict[str, int]
    # Per-class label counts in each split, keyed by class name. The regression
    # guard needs the val counts to decide which classes are well-represented
    # enough to be gated on.
    per_class_counts: dict[str, dict[str, int]]


def _yolo_label_line(class_idx: int, bbox: dict[str, float]) -> str | None:
    """Convert a normalized top-left `{x,y,w,h}` bbox to a YOLO label line."""
    w, h = bbox["w"], bbox["h"]
    if w <= 0.0 or h <= 0.0:
        return None
    xc = min(max(bbox["x"] + w / 2, 0.0), 1.0)
    yc = min(max(bbox["y"] + h / 2, 0.0), 1.0)
    return f"{class_idx} {xc:.6f} {yc:.6f} {min(w, 1.0):.6f} {min(h, 1.0):.6f}"


def _split_frames(frame_ids: list[uuid.UUID]) -> dict[str, list[uuid.UUID]]:
    """Slice a (pre-shuffled) frame-id list into 80/10/10 train/val/test."""
    n = len(frame_ids)
    n_train = int(n * 0.8)
    n_val = int(n * 0.1)
    return {
        "train": frame_ids[:n_train],
        "val": frame_ids[n_train : n_train + n_val],
        "test": frame_ids[n_train + n_val :],
    }


def _link(src: Path, dst: Path) -> None:
    """Symlink `src` into the dataset, copying as a fallback on FS that disallow it."""
    try:
        os.symlink(src, dst)
    except (OSError, NotImplementedError):
        shutil.copy2(src, dst)


def _data_yaml(root: Path, class_names: list[str]) -> str:
    names = "\n".join(f"  {i}: {name}" for i, name in enumerate(class_names))
    return (
        f"path: {root}\n"
        "train: images/train\n"
        "val: images/val\n"
        "test: images/test\n"
        f"names:\n{names}\n"
    )


async def build_yolo_dataset(
    session: AsyncSession, settings: Settings, run_id: uuid.UUID
) -> YoloDatasetManifest:
    """Assemble `training/run_<id>/` as an Ultralytics dataset; return its manifest.

    Frames are split 80/10/10 deterministically (seeded by the run id). The
    class index of each label is the position of its class in the stable
    `(created_at, id)` ordering of active classes.
    """
    classes = list(
        await session.scalars(
            select(Class).where(Class.is_active.is_(True)).order_by(Class.created_at, Class.id)
        )
    )
    class_index = {cls.id: idx for idx, cls in enumerate(classes)}
    class_names = [cls.name for cls in classes]
    class_ids = [cls.id for cls in classes]

    rows = (
        await session.execute(
            select(
                DetectionModel.id,
                DetectionModel.frame_id,
                DetectionModel.class_id,
                DetectionModel.bbox,
                DetectionModel.track_id,
                DetectionModel.confidence_class,
                Frame.path,
            )
            .join(Frame, Frame.id == DetectionModel.frame_id)
            .where(
                DetectionModel.deleted_at.is_(None),
                DetectionModel.class_id.is_not(None),
                Frame.path.is_not(None),
                (DetectionModel.source == "user") | DetectionModel.reviewed.is_(True),
            )
        )
    ).all()

    # Track-aware dedup: a 30-frame walk-through of one object would otherwise
    # emit 30 near-identical YOLO labels and bias the loss. Per
    # `(track_id, class_id)`, keep only the highest-confidence detection
    # (stable tie-break by id). Loose detections (`track_id IS NULL`) are
    # kept verbatim — they're user-drawn or pre-Phase-9 and not part of any
    # over-represented track.
    chosen_per_track: dict[tuple[uuid.UUID, uuid.UUID], tuple[uuid.UUID, float]] = {}
    for det_id, _frame_id, class_id, _bbox, track_id, conf, _path in rows:
        if track_id is None:
            continue
        key = (track_id, class_id)
        score = float(conf) if conf is not None else 0.0
        best = chosen_per_track.get(key)
        if (
            best is None
            or score > best[1]
            or (score == best[1] and det_id < best[0])
        ):
            chosen_per_track[key] = (det_id, score)
    kept_track_det_ids = {rep[0] for rep in chosen_per_track.values()}

    # Group label lines per frame, dropping frames whose JPEG has been pruned.
    labels_by_frame: dict[uuid.UUID, list[str]] = {}
    frame_path: dict[uuid.UUID, str] = {}
    missing: set[uuid.UUID] = set()
    for det_id, frame_id, class_id, bbox, track_id, _conf, path in rows:
        if track_id is not None and det_id not in kept_track_det_ids:
            continue  # collapsed into the chosen rep for this (track, class)
        idx = class_index.get(class_id)
        if idx is None:  # detection of an inactive class — skip
            continue
        if frame_id not in frame_path:
            if frame_id in missing:
                continue
            if not (settings.frames_dir / path).exists():
                missing.add(frame_id)
                continue
            frame_path[frame_id] = path
        line = _yolo_label_line(idx, bbox)
        if line is not None:
            labels_by_frame.setdefault(frame_id, []).append(line)

    frame_ids = sorted(fid for fid, lines in labels_by_frame.items() if lines)
    random.Random(run_id.int).shuffle(frame_ids)
    splits = _split_frames(frame_ids)

    root = settings.models_dir / "training" / f"run_{run_id}"
    if root.exists():
        shutil.rmtree(root)
    for split in _SPLITS:
        (root / "images" / split).mkdir(parents=True, exist_ok=True)
        (root / "labels" / split).mkdir(parents=True, exist_ok=True)

    detections_written = 0
    per_class_counts: dict[str, dict[str, int]] = {
        split: dict.fromkeys(class_names, 0) for split in _SPLITS
    }
    for split, ids in splits.items():
        for fid in ids:
            _link(settings.frames_dir / frame_path[fid], root / "images" / split / f"{fid}.jpg")
            lines = labels_by_frame[fid]
            (root / "labels" / split / f"{fid}.txt").write_text("\n".join(lines) + "\n")
            detections_written += len(lines)
            for line in lines:
                idx = int(line.split(" ", 1)[0])
                per_class_counts[split][class_names[idx]] += 1

    data_yaml = root / "data.yaml"
    data_yaml.write_text(_data_yaml(root, class_names))

    counts = {split: len(ids) for split, ids in splits.items()}
    counts["detections"] = detections_written
    counts["frames_missing"] = len(missing)
    return YoloDatasetManifest(
        root=root,
        data_yaml=data_yaml,
        class_names=class_names,
        class_ids=class_ids,
        counts=counts,
        per_class_counts=per_class_counts,
    )

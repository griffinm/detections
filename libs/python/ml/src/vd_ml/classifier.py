"""Per-class sub-class classifier — logistic regression over crop embeddings.

DB-free, lazy heavy imports. A trained classifier supersedes the bootstrap kNN
in `vd.assign_subclass` (Regime B). Persisted with joblib; one file per
training run so `load_classifier`'s cache never serves a stale model.
"""

from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple


class ClassifierTrainResult(NamedTuple):
    """Outcome of one sub-class classifier training run."""

    val_accuracy: float
    n_train: int
    n_val: int
    subclass_ids: list[str]


def train_subclass_classifier(
    embeddings: list[list[float]],
    labels: list[str],
    out_path: str,
) -> ClassifierTrainResult:
    """Fit a multinomial L2 logistic regression and persist it to `out_path`.

    `labels` are sub-class id strings. With ≥10 samples and ≥2 per class a
    stratified 20% holdout measures accuracy; otherwise accuracy is reported on
    the training set (the dataset is too small to split meaningfully).
    """
    import joblib
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split

    features = np.asarray(embeddings, dtype="float32")
    targets = np.asarray(labels)

    n_classes = len(set(labels))
    min_per_class = min(Counter(labels).values())
    # A stratified holdout needs ≥1 sample per class on each side, so the
    # holdout's absolute size must be ≥ n_classes — a plain 20% fraction can
    # round below that on small/many-class datasets.
    n_val = max(n_classes, round(len(labels) * 0.2))
    if len(labels) >= 10 and min_per_class >= 2 and len(labels) - n_val >= n_classes:
        x_train, x_val, y_train, y_val = train_test_split(
            features, targets, test_size=n_val, random_state=0, stratify=targets
        )
    else:
        x_train, y_train, x_val, y_val = features, targets, features, targets

    # L2 is the default regularization on every supported sklearn version;
    # passing `penalty=` explicitly is deprecated as of sklearn 1.8.
    classifier = LogisticRegression(C=1.0, max_iter=2000)
    classifier.fit(x_train, y_train)
    val_accuracy = float(classifier.score(x_val, y_val))

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(classifier, out_path)

    return ClassifierTrainResult(
        val_accuracy=val_accuracy,
        n_train=len(y_train),
        n_val=len(y_val),
        subclass_ids=[str(c) for c in classifier.classes_],
    )


@lru_cache(maxsize=16)
def load_classifier(weights_path: str) -> Any:
    """Load a persisted classifier, cached per path (process-level singleton)."""
    import joblib

    return joblib.load(weights_path)


def predict_subclass(classifier: Any, embedding: list[float]) -> tuple[str, float]:
    """Return the (subclass_id, probability) the classifier is most confident in."""
    import numpy as np

    proba = classifier.predict_proba(np.asarray([embedding], dtype="float32"))[0]
    best = int(proba.argmax())
    return str(classifier.classes_[best]), float(proba[best])

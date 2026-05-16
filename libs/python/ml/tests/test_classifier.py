"""Round-trip test for the sub-class classifier.

Skipped when scikit-learn / numpy are not installed (the `inference` extra) —
the wrapper imports them lazily, so the rest of `vd_ml` stays light.
"""

import pytest

pytest.importorskip("sklearn")
pytest.importorskip("numpy")

from vd_ml import load_classifier, predict_subclass, train_subclass_classifier

_A = "11111111-1111-1111-1111-111111111111"
_B = "22222222-2222-2222-2222-222222222222"


def test_train_predict_round_trip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # Two well-separated one-hot clusters in 8-d space.
    embeddings: list[list[float]] = []
    labels: list[str] = []
    for _ in range(8):
        embeddings.append([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        labels.append(_A)
        embeddings.append([0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        labels.append(_B)

    out = tmp_path / "clf.joblib"
    result = train_subclass_classifier(embeddings, labels, str(out))

    assert out.exists()
    assert set(result.subclass_ids) == {_A, _B}
    assert result.val_accuracy == pytest.approx(1.0)

    classifier = load_classifier(str(out))
    subclass_id, prob = predict_subclass(classifier, [0.9, 0.1, 0, 0, 0, 0, 0, 0])
    assert subclass_id == _A
    assert prob > 0.5

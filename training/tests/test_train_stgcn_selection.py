from __future__ import annotations

import pytest

from training.train_stgcn import checkpoint_selection_score


def test_checkpoint_selection_can_penalize_unknown_false_accepts() -> None:
    score = checkpoint_selection_score(
        "balanced_accuracy_minus_unknown_far",
        accuracy=0.9,
        balanced_accuracy=0.82,
        unknown_false_accept_rate=0.12,
        unknown_far_penalty=1.5,
    )

    assert score == pytest.approx(0.64)


def test_unknown_aware_selection_requires_unknown_validation_samples() -> None:
    with pytest.raises(ValueError, match="requires validation unknown"):
        checkpoint_selection_score(
            "balanced_accuracy_minus_unknown_far",
            accuracy=0.9,
            balanced_accuracy=0.82,
            unknown_false_accept_rate=None,
            unknown_far_penalty=1.0,
        )


@pytest.mark.parametrize(
    ("metric", "expected"),
    [("accuracy", 0.91), ("balanced_accuracy", 0.77)],
)
def test_existing_selection_metrics_are_unchanged(metric: str, expected: float) -> None:
    assert checkpoint_selection_score(
        metric,
        accuracy=0.91,
        balanced_accuracy=0.77,
        unknown_false_accept_rate=0.2,
        unknown_far_penalty=1.0,
    ) == expected

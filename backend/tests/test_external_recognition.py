import math

from exercises.base import ExerciseType
from recognition.external import parse_external_probabilities
from state_machine.manager import FormManager


def test_external_probabilities_normalize_aliases_and_margin():
    evidence = parse_external_probabilities({
        "push_up": 0.86,
        "plank": 0.08,
        "invented_label": 0.99,
    })

    assert evidence is not None
    assert evidence.top1 == "pushup"
    assert evidence.top2 == "plank"
    assert evidence.margin == 0.78


def test_external_probabilities_reject_non_finite_scores():
    evidence = parse_external_probabilities({"squat": math.nan})
    assert evidence is None


def test_high_confidence_external_evidence_can_supply_missing_candidate():
    manager = FormManager()
    exercise, confidence, source = manager._apply_external_evidence(
        {"plank": 0.91, "push_up": 0.04},
        None,
        0.0,
        "hmm",
    )

    assert exercise == ExerciseType.PLANK
    assert confidence == 0.91
    assert source == "external"


def test_low_margin_external_evidence_is_not_trusted():
    manager = FormManager()
    exercise, confidence, source = manager._apply_external_evidence(
        {"squat": 0.81, "push_up": 0.75},
        ExerciseType.PUSHUP,
        0.65,
        "hmm",
    )

    assert exercise == ExerciseType.PUSHUP
    assert confidence == 0.65
    assert source == "hmm"

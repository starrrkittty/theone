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


def test_bundled_stgcn_labels_map_to_canonical_curl_scope():
    evidence = parse_external_probabilities({
        "curl-stand": 0.84,
        "curl-seat": 0.05,
        "alt-stand": 0.08,
        "alt-seat": 0.03,
    })

    assert evidence is not None
    assert evidence.top1 == "bicep_curl"
    assert evidence.raw_top1 == "curl-stand"
    assert evidence.scope == "curl_only"


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


def test_curl_only_model_cannot_create_curl_from_unknown_motion():
    manager = FormManager()
    exercise, confidence, source = manager._apply_external_evidence(
        {"curl-stand": 0.92, "alt-stand": 0.02},
        None,
        0.0,
        "hmm",
    )

    assert exercise is None
    assert confidence == 0.0
    assert source == "hmm"
    assert manager._last_external_debug["accepted"] is False
    assert manager._last_external_debug["reason"] == "curl_model_requires_curl_candidate"


def test_curl_only_model_can_refine_existing_curl_candidate():
    manager = FormManager()
    exercise, confidence, source = manager._apply_external_evidence(
        {"alt-stand": 0.93, "curl-stand": 0.02},
        ExerciseType.BICEP_CURL,
        0.45,
        "rule_gate",
    )

    assert exercise == ExerciseType.ALTERNATE_BICEP_CURL
    assert confidence == 0.93
    assert source == "external"
    assert manager._last_external_debug["accepted"] is True

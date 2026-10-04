from types import SimpleNamespace

from recognition.semantic import (
    CANDIDATE_STGCN_MODEL_ID,
    SemanticRecognitionTracker,
    is_supported_local_model,
    parse_semantic_probabilities,
    parse_semantic_result,
)
from reporting.builder import ActionReportBuilder
from state_machine.manager import SystemState


def _idle_state():
    return SimpleNamespace(
        system_state=SystemState.SCANNING,
        current_exercise=None,
        candidate_exercise=None,
        candidate_confidence=0.0,
        exercise_confidence=0.0,
        form_confidence=0.0,
        signal_quality="good",
        stable_violations=[],
        exercise_variant=None,
        exercise_source="hmm",
        camera_view="frontal",
        exercise_result=None,
        rejection_reason="unsupported_motion",
    )


def test_semantic_result_resolves_alias_and_safe_fallback():
    evidence = parse_semantic_result({
        "exercise": "保加利亚蹲",
        "confidence": 0.88,
        "source": "video_llm",
    })
    assert evidence.profile.id == "bulgarian_split_squat"
    assert evidence.profile.fallback_specialist == "lower_body_general"
    assert evidence.profile.precise_rep_count is False


def test_local_multiclass_probabilities_can_supply_long_tail_semantics():
    evidence = parse_semantic_probabilities({
        "jumping_jack": 0.86,
        "lunge": 0.09,
        "squat": 0.97,
    })
    assert evidence.profile.id == "jumping_jack"
    assert evidence.confidence == 0.86
    assert evidence.source == "local_stgcn"


def test_local_probabilities_cannot_bypass_core_specialist_guards():
    assert parse_semantic_probabilities({"squat": 0.99, "pushup": 0.01}) is None


def test_local_semantic_probabilities_use_calibrated_class_thresholds():
    assert parse_semantic_probabilities({"lunge": 0.96, "unknown": 0.04}) is None
    evidence = parse_semantic_probabilities({"lunge": 0.98, "unknown": 0.02})
    assert evidence.profile.id == "lunge"


def test_candidate_model_uses_its_own_calibrated_thresholds():
    evidence = parse_semantic_probabilities(
        {"burpee": 0.74, "unknown": 0.26},
        CANDIDATE_STGCN_MODEL_ID,
    )
    assert evidence.profile.id == "burpee"
    assert parse_semantic_probabilities(
        {"pullup": 0.91, "unknown": 0.09},
        CANDIDATE_STGCN_MODEL_ID,
    ) is None
    evidence = parse_semantic_probabilities(
        {"pullup": 0.93, "unknown": 0.07},
        CANDIDATE_STGCN_MODEL_ID,
    )
    assert evidence.profile.id == "pullup"


def test_unregistered_local_model_is_never_trusted():
    assert is_supported_local_model(CANDIDATE_STGCN_MODEL_ID) is True
    assert is_supported_local_model("forged-model") is False
    assert parse_semantic_probabilities(
        {"burpee": 0.99},
        "forged-model",
    ) is None


def test_semantic_tracker_requires_temporal_confirmation():
    tracker = SemanticRecognitionTracker(confirmation_hits=2)
    evidence = parse_semantic_result({
        "exercise_id": "jumping_jack",
        "confidence": 0.9,
    })
    first = tracker.update(evidence, 1000.0, core_confirmed=False)
    second = tracker.update(evidence, 2000.0, core_confirmed=False)
    assert first.confirmed is False
    assert second.confirmed is True


def test_semantic_action_emits_general_coaching_report_without_fake_precision():
    tracker = SemanticRecognitionTracker(confirmation_hits=1)
    evidence = parse_semantic_result({
        "exercise_id": "jumping_jack",
        "confidence": 0.91,
        "source": "video_llm",
    })
    semantic = tracker.update(evidence, 1000.0, core_confirmed=False)
    report, event = ActionReportBuilder("semantic-1").build(
        _idle_state(), 1000.0, semantic=semantic,
    )

    assert report.recognized_exercise == "jumping_jack"
    assert report.routing.mode == "general_coaching"
    assert report.routing.specialist == "cardio_general"
    assert report.capabilities.semantic_recognition is True
    assert report.capabilities.precise_rep_count is False
    assert event is not None
    assert event.route_mode == "general_coaching"


def test_core_recognition_resets_semantic_tracker():
    tracker = SemanticRecognitionTracker(confirmation_hits=1)
    evidence = parse_semantic_result({"exercise_id": "lunge", "confidence": 0.9})
    assert tracker.update(evidence, 1000.0, core_confirmed=False) is not None
    assert tracker.update(None, 1100.0, core_confirmed=True) is None


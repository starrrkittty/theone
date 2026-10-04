from types import SimpleNamespace

from exercises.base import ExerciseResult, ExerciseType, JointAngles
from pipeline.form_evaluator import Violation
from reporting.builder import ActionReportBuilder
from state_machine.manager import SystemState


def _state(*, exercise=ExerciseType.SQUAT, violations=None, confidence=0.88):
    return SimpleNamespace(
        system_state=SystemState.ACTIVE,
        current_exercise=exercise,
        candidate_exercise=exercise,
        candidate_confidence=confidence,
        exercise_confidence=confidence,
        form_confidence=0.84,
        signal_quality="good",
        stable_violations=violations or [],
        exercise_variant=exercise.value,
        exercise_source="fused",
        camera_view="frontal",
        exercise_result=ExerciseResult(
            is_valid=True,
            rep_count=4,
            rep_phase="concentric",
            angles=JointAngles(left_knee=82.0, right_knee=86.0),
            measured_angles={"left_knee": 82.0, "right_knee": 86.0},
            angle_confidences={"left_knee": 0.92, "right_knee": 0.88},
            confidence_method="landmark_visibility_min",
        ),
    )


def test_report_contains_compact_metrics_and_one_time_confirmation_event():
    builder = ActionReportBuilder("session-1")

    report, event = builder.build(_state(), 1234.0)
    second_report, second_event = builder.build(_state(), 1240.0)

    assert report.recognized_exercise == "squat"
    assert report.schema_version == "v2"
    assert report.report_id.endswith(":1")
    assert report.sequence == 1
    assert report.metrics.joint_angles["left_knee"] == 82.0
    assert report.metrics.joint_confidences["left_knee"] == 0.92
    assert report.metrics.confidence_method == "landmark_visibility_min"
    assert report.specialist == "squat_specialist"
    assert report.routing.mode == "verified_specialist"
    assert report.capabilities.precise_rep_count is True
    assert report.capabilities.specialized_form_correction is True
    assert event is not None
    assert event.event == "exercise_confirmed"
    assert "深蹲" in event.message
    assert report.coach_trigger.triggered is True
    assert report.coach_trigger.reason == "exercise_confirmed"
    assert report.coach_trigger.report_id == report.report_id
    assert second_report.recognition_status == "confirmed"
    assert second_report.sequence == 2
    assert second_report.session_generation == report.session_generation
    assert second_report.coach_trigger.triggered is False
    assert second_event is None


def test_unconfirmed_candidate_is_reported_as_unknown():
    state = _state(exercise=ExerciseType.SQUAT)
    state.current_exercise = None
    state.exercise_result = None
    builder = ActionReportBuilder("session-2")

    report, event = builder.build(state, 2000.0)

    assert report.recognition_status == "candidate"
    assert report.recognized_exercise == "unknown"
    assert report.candidate_exercises[0].exercise == "squat"
    assert event is None


def test_reset_starts_a_new_generation_and_restarts_sequence():
    builder = ActionReportBuilder("session-reset")
    before, _ = builder.build(_state(), 1000.0)

    builder.reset()
    after, _ = builder.build(_state(), 2000.0)

    assert after.session_generation != before.session_generation
    assert after.sequence == 1
    assert after.report_id != before.report_id


def test_persistent_form_error_emits_sparse_trigger_after_cooldown():
    builder = ActionReportBuilder("session-form")
    violation = Violation(
        code="knees_caving",
        severity="yellow",
        message="膝盖内扣",
        correction="膝盖对准脚尖",
    )

    first, _ = builder.build(_state(), 1000.0)
    middle, _ = builder.build(_state(violations=[violation]), 2000.0)
    triggered, _ = builder.build(_state(violations=[violation]), 9001.0)
    suppressed, _ = builder.build(_state(violations=[violation]), 9002.0)

    assert first.coach_trigger.reason == "exercise_confirmed"
    assert middle.coach_trigger.triggered is False
    assert triggered.coach_trigger.triggered is True
    assert triggered.coach_trigger.reason == "persistent_form_error"
    assert suppressed.coach_trigger.triggered is False


def test_red_violation_can_emit_immediate_safety_trigger():
    builder = ActionReportBuilder("session-safety")
    builder.build(_state(), 1000.0)
    danger = Violation(
        code="unsafe_spine_position",
        severity="red",
        message="躯干姿态存在安全风险",
        correction="立即停止动作并调整姿势",
    )

    report, _ = builder.build(_state(violations=[danger]), 1100.0)

    assert report.coach_trigger.triggered is True
    assert report.coach_trigger.reason == "safety"
    assert report.coach_trigger.priority == "safety"

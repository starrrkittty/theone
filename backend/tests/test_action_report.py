from types import SimpleNamespace

from exercises.base import ExerciseResult, ExerciseType, JointAngles
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
        ),
    )


def test_report_contains_compact_metrics_and_one_time_confirmation_event():
    builder = ActionReportBuilder("session-1")

    report, event = builder.build(_state(), 1234.0)
    second_report, second_event = builder.build(_state(), 1240.0)

    assert report.recognized_exercise == "squat"
    assert report.metrics.joint_angles["left_knee"] == 82.0
    assert report.specialist == "squat_specialist"
    assert event is not None
    assert event.event == "exercise_confirmed"
    assert "深蹲" in event.message
    assert second_report.recognition_status == "confirmed"
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

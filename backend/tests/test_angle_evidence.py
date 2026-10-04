from exercises.base import ExerciseResult, JointAngles, JointName, Landmark
from exercises.pushup import PushupModule
from exercises.squat import SquatModule


def _visible_landmarks(visibility: float = 0.9):
    return {
        joint: Landmark(x=0.5, y=index / 33.0, z=0.0, visibility=visibility)
        for index, joint in enumerate(JointName)
    }


def _result(**angles):
    return ExerciseResult(
        is_valid=True,
        rep_count=0,
        rep_phase="idle",
        angles=JointAngles(**angles),
    )


def test_squat_exposes_only_declared_measured_angles_with_visibility_confidence():
    module = SquatModule()
    landmarks = _visible_landmarks()
    landmarks[JointName.LEFT_KNEE].visibility = 0.73
    result = _result(
        left_knee=84.0,
        right_knee=87.0,
        left_hip=91.0,
        right_hip=93.0,
        torso_angle=14.0,
        left_elbow=0.0,
    )

    module._attach_angle_evidence(result, landmarks)

    assert set(result.measured_angles) == {
        "left_knee",
        "right_knee",
        "left_hip",
        "right_hip",
        "torso_angle",
    }
    assert result.angle_confidences["left_knee"] == 0.73
    assert result.confidence_method == "landmark_visibility_min"


def test_low_visibility_measurement_is_omitted_instead_of_sent_as_zero():
    module = SquatModule()
    landmarks = _visible_landmarks()
    landmarks[JointName.LEFT_KNEE].visibility = 0.2
    result = _result(left_knee=84.0, right_knee=87.0)

    module._attach_angle_evidence(result, landmarks)

    assert "left_knee" not in result.measured_angles
    assert "left_knee" not in result.angle_confidences
    assert result.measured_angles["right_knee"] == 87.0


def test_pushup_does_not_publish_internal_normalized_torso_deviation_as_degrees():
    module = PushupModule()
    result = _result(left_elbow=88.0, right_elbow=90.0, torso_angle=0.12)

    module._attach_angle_evidence(result, _visible_landmarks())

    assert result.measured_angles["left_elbow"] == 88.0
    assert "torso_angle" not in result.measured_angles

from pathlib import Path

import pytest

from kinematics.urdf_loader import UrdfError, load_urdf


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_load_minimal_human_urdf_and_compact_joint_map():
    model = load_urdf(REPO_ROOT / "assets" / "human_minimal.urdf")

    assert model.name == "ai_coach_human_v1"
    assert len(model.joints) == 6
    assert model.joints["left_knee_joint"].parent == "left_thigh"
    assert model.joints["left_knee_joint"].limit.upper == pytest.approx(2.53)
    assert model.compact_joint_map()["right_ankle_joint"]["axis"] == [0.0, 1.0, 0.0]


def test_validate_landmark_mapping_reports_unknown_joint():
    model = load_urdf(REPO_ROOT / "assets" / "human_minimal.urdf")
    errors = model.validate_mapping({
        "left_knee": "left_knee_joint",
        "left_elbow": "missing_elbow_joint",
    })

    assert errors == ["left_elbow: unknown URDF joint 'missing_elbow_joint'"]


def test_missing_urdf_is_rejected():
    missing = REPO_ROOT / "assets" / "__nonexistent_test_skeleton__.urdf"
    assert not missing.exists()
    with pytest.raises(UrdfError, match="not found"):
        load_urdf(missing)

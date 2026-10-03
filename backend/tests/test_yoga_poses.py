"""Tests for the 8 static yoga pose detectors and the yoga registry.

Each pose gets a synthetic 33-landmark "correct" skeleton (should be detected
as in-pose with no violations) and a "wrong" skeleton (should be rejected with
a violation and a flagged joint color).
"""

import pytest

from exercises.yoga_registry import (
    SUPPORTED_YOGA_LABELS,
    YOGA_POSE_MODULES,
    supported_yoga_payload,
)


def _skeleton(joints: dict[int, tuple[float, float]]) -> list[dict]:
    """Build a 33-landmark list; `joints` overrides specific MediaPipe indices."""
    lms = [{"x": 0.5, "y": 0.5, "z": 0.0, "visibility": 0.9} for _ in range(33)]
    for idx, (x, y) in joints.items():
        lms[idx] = {"x": x, "y": y, "z": 0.0, "visibility": 0.95}
    return lms


# Index legend: 11/12 shoulders, 13/14 elbows, 15/16 wrists,
# 23/24 hips, 25/26 knees, 27/28 ankles.

MOUNTAIN_OK = {
    11: (0.42, 0.25), 12: (0.58, 0.25), 13: (0.40, 0.40), 14: (0.60, 0.40),
    15: (0.40, 0.55), 16: (0.60, 0.55), 23: (0.45, 0.55), 24: (0.55, 0.55),
    25: (0.45, 0.75), 26: (0.55, 0.75), 27: (0.45, 0.95), 28: (0.55, 0.95),
}
MOUNTAIN_BAD = {**MOUNTAIN_OK, 27: (0.60, 0.77), 28: (0.40, 0.77)}  # bent knees

TREE_OK = {
    11: (0.42, 0.25), 12: (0.58, 0.25), 23: (0.45, 0.55), 24: (0.55, 0.55),
    25: (0.45, 0.75), 26: (0.64, 0.64), 27: (0.45, 0.95), 28: (0.47, 0.72),
}
TREE_BAD = {  # both feet planted
    11: (0.42, 0.25), 12: (0.58, 0.25), 23: (0.45, 0.55), 24: (0.55, 0.55),
    25: (0.45, 0.75), 26: (0.55, 0.75), 27: (0.45, 0.95), 28: (0.55, 0.95),
}

WARRIOR1_OK = {
    11: (0.42, 0.25), 12: (0.58, 0.25), 13: (0.43, 0.17), 14: (0.57, 0.17),
    15: (0.44, 0.08), 16: (0.56, 0.08), 23: (0.42, 0.55), 24: (0.55, 0.55),
    25: (0.40, 0.72), 26: (0.58, 0.75), 27: (0.55, 0.74), 28: (0.60, 0.95),
}
WARRIOR1_BAD = {**WARRIOR1_OK, 15: (0.40, 0.55), 16: (0.60, 0.55)}  # arms down

WARRIOR2_OK = {
    11: (0.42, 0.25), 12: (0.58, 0.25), 13: (0.28, 0.25), 14: (0.72, 0.25),
    15: (0.15, 0.25), 16: (0.85, 0.25), 23: (0.42, 0.55), 24: (0.55, 0.55),
    25: (0.40, 0.72), 26: (0.58, 0.75), 27: (0.55, 0.74), 28: (0.60, 0.95),
}
WARRIOR2_BAD = {**WARRIOR2_OK, 15: (0.40, 0.55), 16: (0.60, 0.55)}  # arms down

CHAIR_OK = {
    11: (0.42, 0.25), 12: (0.58, 0.25), 15: (0.44, 0.08), 16: (0.56, 0.08),
    23: (0.45, 0.50), 24: (0.55, 0.50), 25: (0.45, 0.70), 26: (0.55, 0.70),
    27: (0.60, 0.80), 28: (0.40, 0.80),
}
CHAIR_BAD = {  # straight legs, arms up
    11: (0.42, 0.25), 12: (0.58, 0.25), 15: (0.44, 0.08), 16: (0.56, 0.08),
    23: (0.45, 0.55), 24: (0.55, 0.55), 25: (0.45, 0.75), 26: (0.55, 0.75),
    27: (0.45, 0.95), 28: (0.55, 0.95),
}

TRIANGLE_OK = {
    11: (0.30, 0.40), 12: (0.45, 0.35), 15: (0.27, 0.85), 16: (0.50, 0.10),
    23: (0.40, 0.55), 24: (0.60, 0.55), 25: (0.30, 0.72), 26: (0.70, 0.72),
    27: (0.25, 0.92), 28: (0.75, 0.92),
}
TRIANGLE_BAD = {  # upright torso, arms together
    11: (0.42, 0.25), 12: (0.58, 0.25), 15: (0.40, 0.55), 16: (0.60, 0.55),
    23: (0.45, 0.55), 24: (0.55, 0.55), 25: (0.45, 0.75), 26: (0.55, 0.75),
    27: (0.45, 0.95), 28: (0.55, 0.95),
}

DOWNDOG_OK = {
    11: (0.30, 0.45), 12: (0.30, 0.45), 13: (0.25, 0.60), 14: (0.25, 0.60),
    15: (0.20, 0.75), 16: (0.20, 0.75), 23: (0.50, 0.30), 24: (0.50, 0.30),
    25: (0.65, 0.55), 26: (0.65, 0.55), 27: (0.75, 0.75), 28: (0.75, 0.75),
}
DOWNDOG_BAD = {  # flat plank, hips not lifted
    11: (0.30, 0.55), 12: (0.30, 0.55), 13: (0.25, 0.55), 14: (0.25, 0.55),
    15: (0.20, 0.55), 16: (0.20, 0.55), 23: (0.50, 0.55), 24: (0.50, 0.55),
    25: (0.65, 0.55), 26: (0.65, 0.55), 27: (0.75, 0.55), 28: (0.75, 0.55),
}

COBRA_OK = {
    11: (0.35, 0.55), 12: (0.35, 0.55), 23: (0.55, 0.72), 24: (0.55, 0.72),
    25: (0.70, 0.74), 26: (0.70, 0.74), 27: (0.80, 0.74), 28: (0.80, 0.74),
}
COBRA_BAD = {  # flat on floor, chest not lifted
    11: (0.35, 0.74), 12: (0.35, 0.74), 23: (0.55, 0.74), 24: (0.55, 0.74),
    25: (0.70, 0.74), 26: (0.70, 0.74), 27: (0.80, 0.74), 28: (0.80, 0.74),
}

CASES: dict[str, tuple[dict, dict]] = {
    "mountain": (MOUNTAIN_OK, MOUNTAIN_BAD),
    "tree": (TREE_OK, TREE_BAD),
    "warrior_i": (WARRIOR1_OK, WARRIOR1_BAD),
    "warrior_ii": (WARRIOR2_OK, WARRIOR2_BAD),
    "chair": (CHAIR_OK, CHAIR_BAD),
    "triangle": (TRIANGLE_OK, TRIANGLE_BAD),
    "downward_dog": (DOWNDOG_OK, DOWNDOG_BAD),
    "cobra": (COBRA_OK, COBRA_BAD),
}


@pytest.mark.parametrize("label", list(CASES))
def test_correct_pose_is_detected(label):
    ok_joints, _ = CASES[label]
    pose = YOGA_POSE_MODULES[label]()
    ev = pose.process_frame(_skeleton(ok_joints))
    assert ev.is_in_pose, f"{label} should be in-pose; violations={ev.violations}"
    assert ev.violations == []
    assert ev.confidence > 0.0


@pytest.mark.parametrize("label", list(CASES))
def test_wrong_pose_is_rejected(label):
    _, bad_joints = CASES[label]
    pose = YOGA_POSE_MODULES[label]()
    ev = pose.process_frame(_skeleton(bad_joints))
    assert not ev.is_in_pose, f"{label} wrong fixture should be rejected"
    assert ev.violations, f"{label} should report a violation"
    assert any(color in ("red", "yellow") for color in ev.joint_colors.values())


def test_low_visibility_is_not_in_pose():
    pose = YOGA_POSE_MODULES["mountain"]()
    lms = _skeleton(MOUNTAIN_OK)
    for idx in (25, 26, 27, 28):  # hide the legs
        lms[idx]["visibility"] = 0.1
    ev = pose.process_frame(lms)
    assert not ev.is_in_pose
    assert ev.violations


def test_registry_has_exactly_eight_poses():
    assert len(YOGA_POSE_MODULES) == 8
    assert len(SUPPORTED_YOGA_LABELS) == 8
    for label in SUPPORTED_YOGA_LABELS:
        assert YOGA_POSE_MODULES[label]().name == label

    payload = supported_yoga_payload()
    assert len(payload) == 8
    assert {p["label"] for p in payload} == set(SUPPORTED_YOGA_LABELS)
    for entry in payload:
        assert entry["camera_view"] in ("front", "side")
        assert entry["target_hold_seconds"] > 0

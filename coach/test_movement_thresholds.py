import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.engine import InputError, validate_movement
from app.main import app
from app.movement_evidence import measurement_review


def _movement(angle=96, *, exercise="bodyweight_squat", phase="bottom", camera="side", confidence=0.9, definition="included_segment_angle"):
    metric = "left_knee_flexion" if exercise == "bodyweight_squat" else "left_elbow_flexion"
    return {
        "exercise_id": exercise,
        "phase": phase,
        "joints": {metric: {"angle_deg": angle, "confidence": confidence, "definition": definition}},
        "metadata": {"camera_view": camera, "measurement_space": "2d"},
    }


def test_numeric_project_target_reports_within_and_outside_separately():
    inside = measurement_review(_movement(96))["target_checks"][0]
    outside = measurement_review(_movement(110))["target_checks"][0]

    assert inside["status"] == "within_project_target"
    assert inside["observed_deg"] == 96
    assert outside["status"] == "outside_project_target"
    assert "普适动作标准" in outside["caveat"]


def test_target_check_withholds_result_for_wrong_phase_view_confidence_or_definition():
    assert measurement_review(_movement(96, phase="ascent"))["target_checks"][0]["status"] == "insufficient_evidence"
    assert measurement_review(_movement(96, camera="front"))["target_checks"][0]["status"] == "insufficient_evidence"
    assert measurement_review(_movement(96, confidence=0.4))["target_checks"][0]["status"] == "insufficient_evidence"
    assert measurement_review(_movement(96, definition="flexion_from_extension"))["target_checks"][0]["status"] == "insufficient_evidence"


def test_non_numeric_profile_does_not_claim_pass_or_fail():
    result = measurement_review(_movement(90, exercise="goblet_squat"))["target_checks"][0]

    assert result["status"] == "non_numeric_guidance"


def test_single_metric_target_exposes_its_observed_angle():
    movement = _movement(7, exercise="forearm_plank", phase="hold", definition="projected_deviation")
    movement["joints"] = {"trunk_sag_angle": {"angle_deg": 7, "confidence": 0.9, "definition": "projected_deviation"}}

    check = measurement_review(movement)["target_checks"][0]

    assert check["status"] == "within_project_target"
    assert check["observed_deg"] == 7


def test_supported_semantic_action_without_threshold_profile_is_explicitly_qualitative():
    movement = _movement(90, exercise="lunge")
    movement["joints"] = {}

    result = measurement_review(movement)["target_checks"][0]

    assert result["status"] == "non_numeric_guidance"
    assert result["profile_status"] == "not_in_scoped_threshold_set"


def test_reliable_squat_sides_are_aggregated_without_rejecting_a_missing_side():
    movement = _movement(96)
    movement["joints"]["right_knee_flexion"] = {
        "angle_deg": 110,
        "confidence": 0.2,
        "definition": "included_segment_angle",
    }

    check = measurement_review(movement)["target_checks"][0]

    assert check["status"] == "within_project_target"
    assert check["observed_deg"] == 96
    assert set(check["observed_by_metric_deg"]) == {"left_knee_flexion"}
    assert check["excluded_metrics"] == ["right_knee_flexion"]


def test_curl_thresholds_are_checked_independently_per_arm():
    movement = _movement(65, exercise="bicep_curl", phase="ascent")
    movement["joints"]["right_elbow_flexion"] = {
        "angle_deg": 95,
        "confidence": 0.9,
        "definition": "included_segment_angle",
    }

    checks = measurement_review(movement)["target_checks"]

    assert checks[0]["status"] == "outside_project_target"
    assert checks[0]["observed_by_metric_deg"] == {
        "left_elbow_flexion": 65,
        "right_elbow_flexion": 95,
    }


@pytest.mark.parametrize("field,value", [
    ("angle_deg", float("nan")),
    ("angle_deg", float("inf")),
    ("angle_deg", True),
    ("confidence", float("nan")),
    ("confidence", float("inf")),
    ("confidence", True),
])
def test_movement_input_rejects_non_finite_and_boolean_measurements(field, value):
    movement = {
        "schema_version":"1.0", "session_id":"bad-input",
        "timestamp":"2026-10-05T12:00:00+08:00", "exercise_id":"bodyweight_squat",
        "rep_index":1, "phase":"bottom",
        "joints":{"left_knee_flexion":{"angle_deg":96, "confidence":0.9}},
        "metadata":{"camera_view":"side"},
    }
    movement["joints"]["left_knee_flexion"][field] = value

    with pytest.raises(InputError):
        validate_movement(movement)


def test_b_agent_json_cases_through_fastapi_evidence_endpoint():
    expected = {
        "plank_explicit_sag.json":"within_project_target",
        "semantic_lunge.json":"non_numeric_guidance",
        "squat_insufficient_evidence.json":"insufficient_evidence",
        "squat_low_confidence.json":"insufficient_evidence",
        "squat_target_met.json":"within_project_target",
        "squat_target_missed.json":"outside_project_target",
    }
    examples = Path(__file__).parent / "examples" / "b-agent-cases"

    with TestClient(app) as client:
        for filename, status in expected.items():
            payload = json.loads((examples / filename).read_text(encoding="utf-8"))
            response = client.post("/api/v1/movement/evidence", json=payload)

            assert response.status_code == 200, filename
            assert response.json()["measurement_review"]["target_checks"][0]["status"] == status, filename

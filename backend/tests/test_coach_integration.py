import asyncio

from api.coach_bridge import coach_report, normalized_report
from main import app


def _report(exercise="squat", status="confirmed"):
    return {
        "form_confidence": 0.84,
        "action_report": {
            "schema_version": "v2",
            "session_id": "integration-session",
            "report_id": "integration-session:1:7",
            "session_generation": 1,
            "sequence": 7,
            "timestamp_ms": 1_791_043_200_000,
            "recognition_status": status,
            "recognized_exercise": exercise if status == "confirmed" else "unknown",
            "recognition_confidence": 0.91,
            "phase": "eccentric",
            "repetition": 3,
            "pose_quality": "good",
            "camera_view": "profile_left",
            "metrics": {
                "joint_angles": {
                    "left_knee": 96.4,
                    "right_knee": 95.8,
                    "torso_angle": 22.0,
                },
                "joint_confidences": {
                    "left_knee": 0.91,
                    "right_knee": 0.89,
                    "torso_angle": 0.87,
                },
                "confidence_method": "landmark_visibility_min",
                "hold_seconds": 0.0,
                "rep_quality": 0.86,
                "partial_reps": 0,
            },
            "violations": [],
            "agent_context": {"should_coach_now": False},
            "recognition": {"exercise_id": exercise, "source": "semantic_model"},
            "routing": {"mode": "verified_specialist", "specialist": "squat_specialist"},
            "capabilities": {"specialized_form_correction": True},
            "coach_trigger": {
                "triggered": True,
                "reason": "persistent_form_error",
                "priority": "form_correction",
                "recommended_intent": "correct_knees_caving",
                "report_id": "integration-session:1:7",
                "cooldown_ms": 8000,
            },
        },
    }


def test_v2_action_report_normalizes_without_model_call():
    result = normalized_report(_report())

    movement = result["movement"]
    assert result["status"] == "ready"
    assert movement["exercise_id"] == "bodyweight_squat"
    assert movement["phase"] == "descent"
    assert movement["joints"]["left_knee_flexion"]["angle_deg"] == 96.4
    assert movement["joints"]["left_knee_flexion"]["confidence"] == 0.91
    assert movement["metadata"]["measurement_space"] == "2d"
    assert movement["metadata"]["upstream_schema"] == "agent-a/v2"
    assert result["report_id"] == "integration-session:1:7"
    assert result["session_generation"] == 1
    relevant = {row["joint"]:row["relevant_to_specialist"] for row in result["measurement_review"]["measurements"]}
    assert relevant["left_knee_flexion"] is True
    assert relevant["right_knee_flexion"] is True


def test_a_report_returns_deterministic_b_threshold_check():
    result = normalized_report(_report())

    assert result["status"] == "ready"
    checks = result["measurement_review"]["target_checks"]
    assert checks[0]["status"] == "within_project_target"
    assert checks[0]["observed_deg"] == 96.1


def test_plank_proxy_requires_and_accepts_explicit_trunk_sag_metric():
    report = _report(exercise="plank")["action_report"]
    report["phase"] = "hold"
    report["metrics"]["joint_angles"] = {"torso_angle": 14.0, "trunk_sag_angle": 7.0}

    result = normalized_report({"action_report":report, "form_confidence":0.9})

    movement = result["movement"]
    observation = movement["joints"]["trunk_sag_angle"]
    assert observation["definition"] == "projected_deviation"
    assert result["measurement_review"]["target_checks"][0]["status"] == "within_project_target"


def test_bridge_waits_instead_of_calling_model_for_unconfirmed_report():
    result = asyncio.run(coach_report(_report(status="candidate")))

    assert result["status"] == "awaiting_recognition"
    assert result["agent"]["model_called"] is False


def test_bridge_skips_model_when_report_has_no_new_coach_trigger():
    payload = _report()
    payload["action_report"]["coach_trigger"]["triggered"] = False
    payload["action_report"]["coach_trigger"]["reason"] = "none"

    result = asyncio.run(coach_report(payload))

    assert result["status"] == "no_coach_trigger"
    assert result["report_id"] == "integration-session:1:7"
    assert result["agent"]["model_called"] is False


def test_bridge_reports_missing_b_expert_without_calling_model():
    result = asyncio.run(coach_report(_report(exercise="running")))

    assert result["status"] == "expert_unavailable"
    assert result["recognized_exercise"] == "running"
    assert result["agent"]["model_called"] is False


def test_semantic_action_stays_general_and_has_no_form_measurements():
    report = _report(exercise="lunge")
    report["action_report"]["routing"] = {"mode": "general_coaching", "specialist": "lower_body_general"}
    report["action_report"]["capabilities"] = {"specialized_form_correction": False, "precise_rep_count": False}

    result = normalized_report(report)

    assert result["guidance_level"] == "general"
    assert result["movement"]["exercise_id"] == "lunge"
    assert result["movement"]["joints"] == {}
    assert result["measurement_review"]["has_interpretable_specialist_measurement"] is False


def test_semantic_action_cannot_be_promoted_to_specialist():
    report = _report(exercise="squat")
    report["action_report"]["routing"] = {"mode": "general_coaching"}
    report["action_report"]["capabilities"] = {"specialized_form_correction": False}

    from fastapi import HTTPException
    import pytest

    with pytest.raises(HTTPException) as error:
        normalized_report(report)
    assert error.value.status_code == 422


def test_unified_backend_exposes_coach_and_app_contracts():
    paths = app.openapi()["paths"]

    assert "/api/agent-a/normalize" in paths
    assert "/api/agent-a/coach" in paths
    assert "/api/app/v1/capabilities" in paths
    assert "/api/plans/phase" in paths

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


def test_bridge_waits_instead_of_calling_model_for_unconfirmed_report():
    result = asyncio.run(coach_report(_report(status="candidate")))

    assert result["status"] == "awaiting_recognition"
    assert result["agent"]["model_called"] is False


def test_bridge_reports_missing_b_expert_without_calling_model():
    result = asyncio.run(coach_report(_report(exercise="running")))

    assert result["status"] == "expert_unavailable"
    assert result["recognized_exercise"] == "running"
    assert result["agent"]["model_called"] is False


def test_unified_backend_exposes_coach_and_app_contracts():
    paths = app.openapi()["paths"]

    assert "/api/agent-a/normalize" in paths
    assert "/api/agent-a/coach" in paths
    assert "/api/app/v1/capabilities" in paths
    assert "/api/plans/phase" in paths

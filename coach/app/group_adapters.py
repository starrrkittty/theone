from typing import Any

from app.experts.movement import SPECIALISTS


def from_group_a(payload: dict[str, Any]) -> dict[str, Any]:
    """Translate the agreed A-group observation envelope to B-group schema v1."""
    if not isinstance(payload, dict):
        raise ValueError("A 组输入必须是对象。")
    if "action_report" in payload or payload.get("schema_version") in {"v1", "v2"}:
        from app.action_report_adapter import normalize
        return normalize(payload)
    normalized = dict(payload)
    aliases = {"squat": "bodyweight_squat", "lunge": "forward_lunge", "pushup": "push_up"}
    if "exercise_id" not in normalized and "detected_exercise" in normalized:
        normalized["exercise_id"] = aliases.get(normalized["detected_exercise"], normalized["detected_exercise"])
    if "rep_index" not in normalized and "repetition" in normalized:
        normalized["rep_index"] = normalized["repetition"]
    normalized["phase"] = {"descending":"descent", "ascending":"ascent"}.get(normalized.get("phase"), normalized.get("phase", "unknown"))
    normalized.setdefault("schema_version", "1.0")
    normalized.setdefault("phase", "unknown")
    normalized.setdefault("reported_symptoms", [])
    normalized.setdefault("metadata", {})
    if "confidence" in payload and isinstance(normalized["metadata"], dict):
        normalized["metadata"] = {**normalized["metadata"], "classification_confidence":payload["confidence"]}
    return normalized


def from_group_e_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Pick only planning fields; do not forward identity or unrelated profile data."""
    allowed = ("goal", "experience", "days_per_week", "minutes_per_session", "equipment", "limitations", "context", "user_id", "reported_symptoms")
    result = {key: profile[key] for key in allowed if key in profile}
    for source, target in {"available_days":"days_per_week", "session_duration":"minutes_per_session", "injury_notes":"limitations"}.items():
        if target not in result and source in profile:
            result[target] = profile[source]
    return result


def to_group_c_live_event(analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "event": "coach.movement_feedback", "session_id": analysis["session_id"],
        "rep_index": analysis["rep_index"], "exercise_id": analysis["exercise_id"],
        "status": analysis["status"], "cues": analysis["cues"],
        "announcement": "识别到动作：" + analysis["exercise_id"] + "，已匹配 " + "、".join(analysis["routed_to"]) + "。",
        "safety_messages": analysis["safety_messages"],
    }


def to_group_d_view(summary: dict[str, Any]) -> dict[str, Any]:
    """Stable presentation model for D group; presentation labels can be localized in the app."""
    return {
        "title_key": "workout.summary.title", "duration_minutes": summary["duration_minutes"],
        "exercises": summary["completed_exercises"], "sets_completed": summary["sets_completed"],
        "reps_completed": summary["reps_completed"], "highlights": summary["movement_highlights"],
        "next_session": summary["next_session_suggestion"],
    }


def group_e_contract() -> dict[str, Any]:
    return {
        "schema_version": "1.0", "movement_input": "examples/squat_input.json",
        "analysis_output": "examples/squat_output.json", "exercise_ids": sorted({exercise for agent in SPECIALISTS for exercise in agent.supported_exercises}),
        "angle_unit": "degrees", "confidence_range": [0, 1],
        "timestamp": "ISO-8601 with timezone", "unknown_fields": "preserve only in metadata",
    }

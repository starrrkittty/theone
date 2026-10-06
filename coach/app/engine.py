from datetime import datetime
import math
from typing import Any

from app.experts.movement import BY_EXERCISE, catalog
from app.experts.nutrition import SPECIALIST as NUTRITION_EXPERT
from app.experts.planning import SPECIALIST as PLANNING_EXPERT
from app.safety import STOP_SYMPTOMS


class InputError(ValueError):
    pass


def validate_movement(data: dict[str, Any]) -> None:
    required = {"schema_version", "session_id", "timestamp", "exercise_id", "rep_index", "phase", "joints"}
    missing = sorted(required - data.keys())
    if missing:
        raise InputError(f"Missing required fields: {', '.join(missing)}")
    if data["schema_version"] != "1.0":
        raise InputError("Unsupported schema_version")
    if not isinstance(data["timestamp"], str) or not isinstance(data["exercise_id"], str):
        raise InputError("timestamp and exercise_id must be strings")
    try:
        timestamp = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise InputError("timestamp must be ISO-8601") from exc
    if timestamp.tzinfo is None:
        raise InputError("timestamp must include a timezone")
    if not isinstance(data["rep_index"], int) or isinstance(data["rep_index"], bool) or data["rep_index"] < 0:
        raise InputError("rep_index must be a non-negative integer")
    if data["phase"] not in {"descent", "bottom", "ascent", "hold", "unknown"}:
        raise InputError("phase is not a supported value")
    if not isinstance(data["joints"], dict):
        raise InputError("joints must be an object")
    for name, joint in data["joints"].items():
        if not isinstance(joint, dict) or "angle_deg" not in joint:
            raise InputError(f"joints.{name} must contain angle_deg")
        angle = joint["angle_deg"]
        confidence = joint.get("confidence", 1.0)
        if type(angle) not in {int, float} or not math.isfinite(angle) or not 0 <= angle <= 360:
            raise InputError(f"joints.{name}.angle_deg must be between 0 and 360")
        if type(confidence) not in {int, float} or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise InputError(f"joints.{name}.confidence must be between 0 and 1")


def analyze_movement(data: dict[str, Any]) -> dict[str, Any]:
    validate_movement(data)
    exercise_id = data["exercise_id"]
    specialist = BY_EXERCISE.get(exercise_id)
    if specialist is None:
        raise InputError(f"Unsupported exercise_id: {exercise_id}")

    reported = {str(item).strip().lower() for item in data.get("reported_symptoms", [])}
    if reported & STOP_SYMPTOMS:
        return {
            "schema_version": "1.0", "session_id": data["session_id"], "rep_index": data["rep_index"],
            "exercise_id": exercise_id, "routed_to": [specialist.specialist_id], "status": "stop",
            "overall_score": None, "findings": [], "cues": [],
            "safety_messages": ["Stop the exercise now. Seek appropriate medical help for severe, persistent, or concerning symptoms."],
            "limitations": ["Movement feedback is suppressed while a stop symptom is reported."],
            "missing_observations": [],
        }

    findings = specialist.analyze(data)
    measured = [joint.get("confidence", 1.0) for joint in data["joints"].values()]
    low_confidence = not measured or max(measured) < 0.55
    cues = []
    if low_confidence:
        cues.append({"priority": 1, "text": "The pose estimate is unclear; adjust the camera view and repeat before relying on form feedback.", "rationale": "Low-confidence pose landmarks can make angle-based feedback unreliable."})
    for finding in findings:
        cues.append({"priority": 2, "text": finding.pop("cue"), "rationale": f"Observed {finding['joint']}={finding['observed']} degrees at confidence {finding['confidence']:.2f}. This is a review cue, not a diagnosis."})

    assessed_rule_names = {rule.joint for rule in specialist.rules}
    available_evidence = any(name in data["joints"] and data["joints"][name].get("confidence", 1.0) >= 0.55 for name in assessed_rule_names)
    limited = low_confidence or not available_evidence
    # Scoring is withheld: camera-only angles do not support a general movement-quality score.
    return {
        "schema_version": "1.0", "session_id": data["session_id"], "rep_index": data["rep_index"],
        "exercise_id": exercise_id, "routed_to": [specialist.specialist_id],
        "status": "limited" if limited else "assessed", "overall_score": None,
        "findings": findings, "cues": cues, "safety_messages": [],
        "limitations": ["Angle-only pose data cannot establish pain, load, balance, or full movement quality.",
                        "This specialist evaluates only the listed observations; unmeasured criteria are not inferred."],
        "missing_observations": [name for name in specialist.required_observations if name not in data["joints"]],
    }


def experts_catalog() -> dict[str, Any]:
    return {"specialists": catalog(), "task_agents": [
        {"specialist_id": PLANNING_EXPERT["specialist_id"], "skill": PLANNING_EXPERT["skill"], "scope": PLANNING_EXPERT["instructions"]},
        {"specialist_id": "report_agent", "skill": "training-report"},
        {"specialist_id": NUTRITION_EXPERT["specialist_id"], "skill": NUTRITION_EXPERT["skill"], "scope": NUTRITION_EXPERT["instructions"]},
        {"specialist_id": "personal_fitness_coach", "skill": "fitness-chat", "scope": "Local profile/history-aware conversation; no diagnosis or invented observations."}],
        "runtime": "model-backed bounded Agent workflow"}

from datetime import datetime
from typing import Any


GOAL_FOCUS = {
    "general_fitness": "Build a consistent base with whole-body movement patterns.",
    "strength": "Practice major movement patterns with gradual, recoverable progression.",
    "fat_loss": "Pair sustainable activity with a gradual, maintainable lifestyle approach.",
    "mobility": "Use comfortable active ranges and progress without forcing end positions.",
    "endurance": "Build aerobic volume progressively at a conversational starting effort.",
}


def phase_plan(request: dict[str, Any]) -> dict[str, Any]:
    goal = request["goal"]
    experience = request.get("experience", "beginner")
    session_template = _session_template(goal, experience, request.get("equipment", []), request.get("minutes_per_session", 30))
    return {
        "schema_version": "1.0", "phase": "foundation", "duration_weeks": 4,
        "goal": request["goal"], "weekly_sessions": request["days_per_week"],
        "minutes_per_session": request["minutes_per_session"], "focus": GOAL_FOCUS[request["goal"]],
        "weekly_structure": _weekly_structure(request["days_per_week"], goal),
        "session_template": session_template,
        "progression_rule": "Increase only one training variable at a time after repeatable sessions feel controlled and recovery is adequate.",
        "limitations": request.get("limitations", []),
        "review_note": "Template recommendation; adapt for health history and individual needs with a qualified professional.",
    }


def _session_template(goal: str, experience: str, equipment: list[str], minutes: int) -> dict[str, Any]:
    if goal == "endurance":
        return {
            "warmup_minutes": 5, "main": [{"type": "easy_aerobic", "minutes": max(5, minutes - 10), "effort": "conversational"}],
            "cooldown_minutes": 5, "progression": "Add a few comfortable minutes after repeatable sessions; keep most work easy at first.",
        }
    if goal == "mobility":
        return {
            "warmup_minutes": 3, "main": [
                {"pattern": "ankle_knee_to_wall", "sets": 2, "reps": "6-8 each side", "range": "comfortable"},
                {"pattern": "hip_rock_back", "sets": 2, "reps": "6-8", "range": "comfortable"},
                {"pattern": "thoracic_rotation", "sets": 2, "reps": "6 each side", "range": "comfortable"},
            ], "cooldown_minutes": 2,
            "progression": "Increase comfortable range gradually; never force a painful end position.",
        }
    sets = 1 if experience == "beginner" else 2
    if experience == "advanced":
        sets = 3
    squat = "sit_to_stand" if experience == "beginner" else "bodyweight_squat"
    press = "wall_push_up" if experience == "beginner" else "incline_push_up"
    row = "resistance_band_row" if "resistance_band" in equipment else "supported_row_variation"
    return {
        "warmup_minutes": 5,
        "main": [
            {"pattern": "squat", "exercise_option": squat, "sets": sets, "reps": "6-12", "effort_target": "comfortable, leave several repetitions in reserve"},
            {"pattern": "hip_hinge", "exercise_option": "hip_hinge_practice", "sets": sets, "reps": "6-10", "effort_target": "controlled"},
            {"pattern": "horizontal_push", "exercise_option": press, "sets": sets, "reps": "6-12", "effort_target": "comfortable"},
            {"pattern": "horizontal_pull", "exercise_option": row, "sets": sets, "reps": "8-12", "effort_target": "comfortable"},
            {"pattern": "trunk_stability", "exercise_options": ["dead_bug", "short_plank"], "sets": sets, "reps": "6-10 each side or 10-20 seconds", "effort_target": "stop while position remains controlled"},
        ],
        "rest_between_sets_seconds": "60-120, longer if needed to recover",
        "cooldown_minutes": 3,
        "time_note": "If the template does not fit the available time, do fewer sets; keep technique and recovery ahead of completing every item.",
    }


def _weekly_structure(days: int, goal: str) -> list[dict[str, Any]]:
    slots = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    session_type = {"endurance": "easy_aerobic", "mobility": "mobility_and_strength"}.get(goal, "full_body_strength")
    session_days = {slots[min(6, round(index * 7 / days))] for index in range(days)}
    return [{"day": day, "type": session_type if day in session_days else "rest_or_easy_walk"} for day in slots]


def nutrition_advice(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("medical_conditions"):
        return {"schema_version": "1.0", "status": "refer", "message": "For a medical condition, coordinate nutrition changes with a registered dietitian or clinician.", "suggestions": [], "source_ids": []}
    preferences = request.get("dietary_preferences", [])
    allergies = request.get("allergies", [])
    return {
        "schema_version": "1.0", "status": "general_guidance",
        "message": "General population guidance only; this is not a calorie prescription or medical nutrition therapy.",
        "suggestions": [
            "Build meals around a variety of vegetables and fruits, staple grains, and suitable protein sources.",
            "Choose mostly minimally processed foods and a sustainable pattern that fits preferences and budget.",
            "For training, use familiar food and fluids that sit comfortably; fixed timing or fluid targets are not universal.",
        ],
        "dietary_preferences": preferences, "exclude_allergens": allergies,
        "source_ids": ["who_healthy_diet_2024", "acsm_nutrition_exercise_2016"],
    }


def workout_summary(session_id: str, request: dict[str, Any]) -> dict[str, Any]:
    started = datetime.fromisoformat(request["started_at"].replace("Z", "+00:00"))
    ended = datetime.fromisoformat(request["ended_at"].replace("Z", "+00:00"))
    if started.tzinfo is None or ended.tzinfo is None:
        raise ValueError("训练时间必须包含时区")
    if ended < started:
        raise ValueError("ended_at must be after started_at")
    sets = request.get("sets", [])
    rpe = [item["perceived_effort"] for item in sets if item.get("perceived_effort") is not None]
    observations = request.get("movement_observations", [])
    caution_count = sum(1 for item in observations if item.get("status") == "caution")
    stop_symptoms = {"sharp_pain", "chest_pain", "dizziness", "breathing_difficulty", "faintness"}
    reported = {str(item).lower() for item in request.get("reported_symptoms", [])}
    stop_reported = bool(reported & stop_symptoms)
    return {
        "schema_version": "1.0", "session_id": session_id,
        "duration_minutes": round((ended - started).total_seconds() / 60),
        "completed_exercises": sorted({item["exercise_id"] for item in sets}),
        "sets_completed": request.get("sets_completed", len(sets)), "reps_completed": sum(item.get("reps", 0) for item in sets),
        "incomplete_targets": [item["exercise_id"] for item in sets if item.get("target_reps") is not None and item.get("reps", 0) < item["target_reps"]],
        "average_perceived_effort": round(sum(rpe) / len(rpe), 1) if rpe else None,
        "movement_highlights": [item.get("summary") for item in observations if item.get("summary")],
        "caution_observations": caution_count,
        "recovery_check": request.get("recovery_check", "not_provided"),
        "reported_stop_symptom": stop_reported,
        "user_feedback": request.get("user_feedback", []),
        "next_session_suggestion": _next_session(request, stop_reported),
        "disclaimer": "Summarizes submitted records; it does not diagnose injury or infer unreported performance.",
    }


def _next_session(request: dict[str, Any], stop_reported: bool) -> str:
    if stop_reported:
        return "Stop training and seek appropriate medical help for severe or persistent symptoms. Do not progress the plan until this is resolved."
    if request.get("recovery_check") == "pain":
        return "Pause the painful exercise; seek professional advice if pain is sharp, worsening, or persistent. Resume only with comfortable movement."
    if request.get("recovery_check") == "poor":
        return "Keep the next session easy or rest; review any persistent pain with a qualified professional before resuming progression."
    return "Repeat a comfortable, controlled session; progress only one variable if recovery is good and the work felt manageable."

import math


def string():
    return {"type": "string"}


def array(item):
    return {"type": "array", "items": item}


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties)}


NUMBER = {"type": "number"}
INTEGER = {"type": "integer", "minimum": 0}
NULL_NUMBER = {"type": ["number", "null"]}
STRINGS = array(string())
FINDING = obj({"code": string(), "severity": {"type": "string", "enum": ["info", "caution"]},
               "joint": {"type": ["string", "null"]}, "observed": {"type": ["number", "string", "null"]},
               "expected": string(), "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "source_ids": STRINGS})
CUE = obj({"priority": {"type": "integer", "minimum": 1, "maximum": 5}, "text": string(), "rationale": string()})
MOVEMENT = obj({"schema_version": {"const": "1.0"}, "session_id": string(), "rep_index": INTEGER,
                "exercise_id": string(), "routed_to": STRINGS, "status": {"enum": ["assessed", "limited"]},
                "overall_score": {"type": "null"}, "findings": array(FINDING), "cues": array(CUE),
                "safety_messages": STRINGS, "limitations": STRINGS, "missing_observations": STRINGS})
PLAN = obj({"schema_version": {"const": "1.0"}, "phase": {"enum": ["adaptation", "foundation", "specialized", "consolidation"]}, "duration_weeks": {"type": "integer", "minimum": 1, "maximum": 12},
            "goal": string(), "weekly_sessions": {"type": "integer", "minimum": 1, "maximum": 7}, "minutes_per_session": INTEGER,
            "focus": string(), "weekly_structure": array(obj({"day": {"enum": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}, "type": string()})),
            "session_template": obj({"warmup_minutes": INTEGER, "main": array(obj({"pattern": string(), "exercise_option": string(),
                "sets": {"type": "integer", "minimum": 1, "maximum": 8}, "reps": string(), "effort_target": string()})), "cooldown_minutes": INTEGER}),
            "progression_rule": string(), "limitations": STRINGS, "review_note": string()})
NUTRITION = obj({"schema_version": {"const": "1.0"}, "status": {"const": "general_guidance"}, "message": string(),
                 "suggestions": STRINGS, "dietary_preferences": STRINGS, "exclude_allergens": STRINGS, "source_ids": STRINGS,
                 "meals": array(obj({"type": string(), "suggestion": string(), "reason": string()})),
                 "substitutions": STRINGS, "training_day_advice": string(), "hydration_note": string()})
REPORT = obj({"schema_version": {"const": "1.0"}, "session_id": string(), "duration_minutes": INTEGER,
              "completed_exercises": STRINGS, "sets_completed": INTEGER, "reps_completed": INTEGER, "incomplete_targets": STRINGS,
              "average_perceived_effort": NULL_NUMBER, "movement_highlights": STRINGS, "caution_observations": INTEGER,
              "recovery_check": string(), "reported_stop_symptom": {"type": "boolean"}, "user_feedback": STRINGS,
              "next_session_suggestion": string(), "disclaimer": string()})
CONTRACTS = {"movement": MOVEMENT, "plan": PLAN, "report": REPORT, "nutrition": NUTRITION}


def validate(value, schema, path="output"):
    if "const" in schema and value != schema["const"]:
        raise ValueError(f"{path}: expected {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: unsupported enum value")
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    checks = {"object": isinstance(value, dict), "array": isinstance(value, list), "string": isinstance(value, str),
              "number": isinstance(value, (int, float)) and not isinstance(value, bool),
              "integer": isinstance(value, int) and not isinstance(value, bool), "boolean": isinstance(value, bool), "null": value is None}
    if types and not any(checks[kind] for kind in types):
        raise ValueError(f"{path}: incorrect type")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise ValueError(f"{path}: non-finite number")
        if value < schema.get("minimum", float("-inf")) or value > schema.get("maximum", float("inf")):
            raise ValueError(f"{path}: outside allowed range")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError(f"{path}.{key}: missing required field")
        for key, child in schema.get("properties", {}).items():
            if key in value:
                validate(value[key], child, f"{path}.{key}")
    if isinstance(value, list):
        for index, child in enumerate(value):
            validate(child, schema.get("items", {}), f"{path}[{index}]")

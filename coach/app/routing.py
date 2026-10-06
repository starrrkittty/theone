"""Resolve and describe the deterministic B-group movement dispatch path."""

import json
from copy import deepcopy

from app.agent_tools import load_skill, retrieve_knowledge
from app.engine import validate_movement
from app.experts.nutrition import SPECIALIST as NUTRITION_EXPERT
from app.experts.planning import SPECIALIST as PLANNING_EXPERT
from app.experts.movement import BY_EXERCISE
from app.group_adapters import from_group_a
from app.history import memory_context
from app.movement_evidence import measurement_review
from app.safety import STOP_SYMPTOMS


def resolve_movement(payload):
    normalized = from_group_a(payload)
    validate_movement(normalized)
    specialist = BY_EXERCISE.get(normalized["exercise_id"])
    if specialist is None:
        raise ValueError("不支持的动作类型。")
    knowledge = retrieve_knowledge(
        "movement", specialist.specialist_id,
        json.dumps(normalized, ensure_ascii=False), normalized["exercise_id"],
    )
    evidence = measurement_review(normalized)
    return normalized, {
        "task": "movement",
        "exercise_id": normalized["exercise_id"],
        "specialist_id": specialist.specialist_id,
        "specialist_scope": specialist.description,
        "guidance_level": specialist.guidance_level,
        "required_observations": list(specialist.required_observations),
        "skill": "movement-report",
        "skill_loaded": bool(load_skill("movement-report")),
        "knowledge": [
            {"id": item["source_id"], "title": item["source"].get("title"),
             "review_status": item["source"].get("review_status"), "url": item["source"].get("url")}
            for item in knowledge
        ],
        "measurement_review": evidence,
        "model_called": False,
    }


def resolve_task(task, payload):
    """Preview a task's expert, Skill, knowledge, and consented local context."""
    if task not in {"plan", "nutrition", "report"} or not isinstance(payload, dict):
        raise ValueError("任务路由输入无效。")
    effective = deepcopy(payload)
    memory = memory_context(effective["user_id"]) if effective.get("user_id") else {"profile": {}, "recent_records": [], "recent_reports": []}
    profile = memory.get("profile", {})
    defaults = {
        "plan": ("goal", "experience", "days_per_week", "minutes_per_session", "equipment", "limitations"),
        "nutrition": ("goal", "dietary_preferences", "allergies", "medical_conditions", "preferred_foods", "disliked_foods", "budget", "cooking_access"),
    }.get(task, ())
    used_profile = []
    for key in defaults:
        if key not in effective and key in profile:
            effective[key] = profile[key]
            used_profile.append(key)

    from app.agents import service
    service._validate_input(task, effective)

    if task == "plan":
        expert = PLANNING_EXPERT
        skill_name = expert["skill"]
        instructions = "按用户目标、每周天数、单次时长、器材、限制和近期恢复制定可执行的渐进计划。"
        input_summary = {
            "goal": effective.get("goal"), "experience": effective.get("experience", "beginner"),
            "days_per_week": effective.get("days_per_week"), "minutes_per_session": effective.get("minutes_per_session"),
            "equipment": effective.get("equipment", []), "limitations": effective.get("limitations", []),
        }
        knowledge_task = "plan"
    elif task == "nutrition":
        expert = NUTRITION_EXPERT
        skill_name = expert["skill"]
        instructions = "提供保留过敏与偏好的普通饮食建议；医疗营养问题转介专业人员。"
        input_summary = {key: effective.get(key, [] if key in {"dietary_preferences", "allergies", "medical_conditions", "preferred_foods", "disliked_foods"} else None)
                         for key in ("goal", "dietary_preferences", "allergies", "medical_conditions", "preferred_foods", "disliked_foods", "budget", "cooking_access")}
        knowledge_task = "nutrition"
    else:
        expert = {"specialist_id": "report_agent", "skill": "training-report"}
        skill_name = expert["skill"]
        instructions = "汇总程序计算的训练事实，并结合用户反馈给出保守的下次训练建议。"
        input_summary = {key: effective.get(key) for key in ("session_id", "started_at", "ended_at", "sets", "recovery_check", "reported_symptoms") if key in effective}
        knowledge_task = "report"

    specialist = expert["specialist_id"]
    knowledge = retrieve_knowledge(knowledge_task, specialist, json.dumps(effective, ensure_ascii=False))
    symptoms = {str(item).strip().lower() for item in effective.get("reported_symptoms", [])}
    safety_gate = None
    if task == "nutrition" and effective.get("medical_conditions"):
        safety_gate = "medical_nutrition_referral"
    elif task == "plan" and symptoms & STOP_SYMPTOMS:
        safety_gate = "reported_symptom_review"

    return effective, {
        "task": task,
        "specialist_id": specialist,
        "specialist_scope": instructions,
        "skill": skill_name,
        "skill_loaded": bool(load_skill(skill_name)),
        "knowledge": [
            {"id": item["source_id"], "title": item["source"].get("title"),
             "review_status": item["source"].get("review_status"), "url": item["source"].get("url")}
            for item in knowledge
        ],
        "input_summary": input_summary,
        "memory_used_profile_fields": used_profile,
        "recent_workout_records": len(memory.get("recent_reports", [])),
        "safety_gate": safety_gate,
        "model_called": False,
    }

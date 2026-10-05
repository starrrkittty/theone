"""Explicit Agent-A to Agent-B integration endpoints."""

import asyncio
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException


COACH_ROOT = Path(__file__).resolve().parents[2] / "coach"
if str(COACH_ROOT) not in sys.path:
    sys.path.insert(0, str(COACH_ROOT))

from app.action_report_adapter import normalize, report_from  # noqa: E402
from app.engine import InputError, validate_movement  # noqa: E402
from app.movement_evidence import measurement_review  # noqa: E402
from app.routers import run  # noqa: E402


router = APIRouter(prefix="/agent-a", tags=["Agent A to B"])


def _normalized(payload: dict) -> dict:
    movement = normalize(payload)
    validate_movement(movement)
    return movement


@router.post("/normalize")
def normalized_report(payload: dict):
    """Inspect the deterministic v1/v2 mapping without calling a model."""
    try:
        report = report_from(payload)
        movement = _normalized(payload)
        return {
            "status": "ready",
            "report_id": report.get("report_id"),
            "session_generation": report.get("session_generation"),
            "guidance_level": movement["metadata"]["guidance_level"],
            "movement": movement,
            "measurement_review": measurement_review(movement),
        }
    except (InputError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/coach")
async def coach_report(payload: dict):
    """Route a confirmed A report to B's bounded movement Agent."""
    try:
        report = report_from(payload)
        if report.get("recognition_status") != "confirmed":
            return {
                "status": "awaiting_recognition",
                "report_id": report.get("report_id"),
                "message": "等待 A 端稳定确认动作。",
                "agent": {"model_called": False},
            }
        trigger = report.get("coach_trigger")
        user_initiated = payload.get("user_initiated") is True
        if (
            isinstance(trigger, dict)
            and trigger.get("triggered") is False
            and not user_initiated
        ):
            return {
                "status": "no_coach_trigger",
                "report_id": report.get("report_id"),
                "message": "本帧没有新的教练事件；不重复调用模型。",
                "agent": {"model_called": False},
            }
        try:
            movement = _normalized(payload)
        except InputError as exc:
            if str(exc).startswith("B 组暂不支持动作专家："):
                return {
                    "status": "expert_unavailable",
                    "report_id": report.get("report_id"),
                    "recognized_exercise": report.get("recognized_exercise"),
                    "message": str(exc),
                    "agent": {"model_called": False},
                }
            raise
        result = await asyncio.to_thread(run, "movement", movement)
        return {
            "status": "completed",
            "report_id": report.get("report_id"),
            "session_generation": report.get("session_generation"),
            "guidance_level": movement["metadata"]["guidance_level"],
            "normalized_movement": movement,
            "analysis": result,
        }
    except HTTPException:
        raise
    except (InputError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc

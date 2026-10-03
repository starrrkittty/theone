from fastapi import APIRouter, HTTPException
from app.action_report_adapter import normalize, report_from
from app.routers import run
from app.engine import validate_movement
from app.movement_evidence import measurement_review
import asyncio
import time
from api.perception_routes import review_session, review_json
from api.routes import manager
from schemas.action_report import ActionReport

router = APIRouter()


@router.post("/agent-a/normalize")
def normalized_report(payload: dict):
    try:
        movement = normalize(payload)
        validate_movement(movement)
        return {"movement":movement, "measurement_review":measurement_review(movement)}
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/agent-a/coach")
async def coach_report(payload: dict):
    leased_session = None
    try:
        report = report_from(payload)
        if report.get("recognition_status") != "confirmed":
            return {"status":"awaiting_recognition", "message":"等待 A 组确认动作。", "agent":{"model_called":False}}
        perception = report.get("perception_agent", {})
        if not isinstance(perception, dict):
            raise ValueError("perception_agent 必须是对象。")
        if perception and perception.get("handoff_allowed") is not True:
            return {"status":"awaiting_evidence", "message":"A Agent 正在等待可靠观测。", "agent":{"model_called":False}}
        reviewed = None
        live = manager.perception_sessions.get(report.get("session_id"))
        request_generation = live.generation if live else None
        if live:
            try:
                latest = live.snapshot()["action_report"]
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            if latest["recognized_exercise"] != report["recognized_exercise"]:
                return {"status":"awaiting_evidence", "message":"动作已切换，请使用当前报告。"}
            if live.coaching:
                raise HTTPException(429, "该会话已有专家处理请求，请等待结果。")
            live.coaching = True
            leased_session = live
        if report.get("kinematics"):
            if live:
                reviewed = await review_session(report["session_id"])
            else:
                reviewed = await review_json(ActionReport.model_validate(report))
            if reviewed["status"] not in {"completed", "historical_review"} or not reviewed["perception_agent"]["handoff_allowed"]:
                return {"status":"awaiting_evidence", "message":"A Agent 需要更多证据或新观测。", "perception_review":reviewed}
            payload = {**payload, "action_report":reviewed["action_report"]}
        movement = normalize(payload)
        validate_movement(movement)
        result = await asyncio.to_thread(run, "movement", movement)
        current = live.latest["action_report"] if live and live.latest else None
        fresh = (current is not None and manager.perception_sessions.get(report["session_id"]) is live
                 and live.generation == request_generation and time.monotonic()-live.updated_at <= 10
                 and current["recognized_exercise"] == report["recognized_exercise"]
                 and abs(current["timestamp_ms"]-payload.get("action_report", report)["timestamp_ms"]) <= 15_000
                 and current.get("perception_agent", {}).get("handoff_allowed") is True)
        return {"status":"completed" if not live or fresh else "historical_feedback",
                "feedback_scope":"live_snapshot" if fresh else "historical",
                "normalized_movement":movement, "analysis":result, "perception_review":reviewed,
                **({"message":"观测已经变化；该评价基于历史报告。"} if live and not fresh else {})}
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        if leased_session:
            leased_session.coaching = False

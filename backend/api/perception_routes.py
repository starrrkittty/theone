import asyncio
import time
from copy import deepcopy

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from api.routes import manager
from app.model_client import ModelClient, ModelError, ConfigurationError
from perception.agent import PerceptionAgent, PerceptionSession, snapshot_from_report
from kinematics.urdf_loader import parser_backend
from kinematics.urdf_loader import parse_urdf, UrdfError
from kinematics.fitting import forward_kinematics
from schemas.action_report import ActionReport
from pydantic import BaseModel, Field
import math


class UrdfPayload(BaseModel):
    urdf_xml: str = Field(max_length=250_000)
    joint_positions: dict[str, float] = Field(default_factory=dict, max_length=100)

router = APIRouter()


@router.post("/agent-a/urdf/parse")
def parse_model(payload: UrdfPayload):
    try:
        model = parse_urdf(payload.urdf_xml)
        for name, value in payload.joint_positions.items():
            if name not in model.joints or not math.isfinite(value):
                raise ValueError("Joint states must reference known joints with finite values")
            joint = model.joints[name]
            if joint.joint_type == "fixed":
                raise ValueError("Fixed joints cannot receive joint positions")
            if ((joint.limit.lower is not None and value < joint.limit.lower) or
                    (joint.limit.upper is not None and value > joint.limit.upper)):
                raise ValueError("Joint position is outside model limits")
        return {"parser": parser_backend(), "name": model.name, "structure": model.compact_joint_map(),
                "link_transforms": {name: matrix.tolist() for name, matrix in forward_kinematics(model, payload.joint_positions).items()},
                "position_units": {name: "meters" if joint.joint_type == "prismatic" else "radians" for name, joint in model.joints.items() if joint.joint_type != "fixed"},
                "limitations": ["Model limits are not fitness recommendations.", "Input units/calibration must be established by its producer."]}
    except (UrdfError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/agent-a/review-json")
async def review_json(report: ActionReport):
    try:
        snapshot = snapshot_from_report(report)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        result = await asyncio.to_thread(PerceptionAgent().run, snapshot)
        result["status"] = "historical_review"
        return result
    except ConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    except ModelError as exc:
        raise HTTPException(502, str(exc)) from exc


def session_for(client_id):
    session = manager.perception_sessions.get(client_id)
    if session is None:
        raise HTTPException(404, "Pose session is not connected")
    return session


@router.get("/agent-a/status")
def agent_status():
    try:
        model = ModelClient().status()
    except ConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"model": model, "skill": "perception-urdf", "live_mode": "local_policy",
            "model_review": "compact_evidence_with_bounded_tools", "sessions": list(manager.perception_sessions),
            "optimization": {"normal_model_calls": 1, "max_model_calls": 3, "review_cache_seconds": 45,
                             "model_review_interval_seconds": 20, "cache_invalidates_on_evidence_change": True},
            "tools": ["fit_skeleton", "parse_urdf", "forward_kinematics", "inspect_urdf",
                      "inspect_motion", "inspect_visibility", "inspect_recognition"],
            "measurement_calibrated": False, "parser": parser_backend()}


@router.get("/agent-a/sessions/{client_id}")
def session_snapshot(client_id: str, historical: bool = False):
    try:
        session = session_for(client_id)
        snapshot = deepcopy(session.latest) if historical else session.snapshot()
        if snapshot is None:
            raise ValueError("No captured pose to export")
        snapshot.pop("urdf_xml", None)
        snapshot["historical_export"] = historical
        return snapshot
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/agent-a/sessions/{client_id}/urdf")
def export_urdf(client_id: str):
    try:
        snapshot = session_for(client_id).snapshot()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not snapshot["urdf_xml"]:
        raise HTTPException(409, "No visible skeleton to export")
    return Response(snapshot["urdf_xml"], media_type="application/xml",
                    headers={"Content-Disposition": 'attachment; filename="observed-human.urdf"'})


@router.post("/agent-a/sessions/{client_id}/review")
async def review_session(client_id: str):
    session = session_for(client_id)
    if session.reviewing:
        raise HTTPException(409, "An Agent review is already running")
    try:
        snapshot = session.snapshot()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        configured = ModelClient().status()["configured"]
    except ConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    if not configured:
        raise HTTPException(503, "Configure coach/config.json API key to run the AI Agent")
    cached = session.cached_review(snapshot)
    if cached:
        return cached
    if time.monotonic()-session.last_review_at < 20:
        raise HTTPException(429, "Evidence changed; wait for the 20-second model review interval")
    session.reviewing = True
    session.last_review_at = time.monotonic()
    try:
        result = await asyncio.to_thread(PerceptionAgent().run, snapshot)
        current = manager.perception_sessions.get(client_id)
        current_report = current.latest["action_report"] if current and current.latest else None
        fresh = (current is session and snapshot["generation"] == session.generation
                 and time.monotonic()-session.updated_at <= 10 and current_report is not None
                 and current_report["recognized_exercise"] == snapshot["action_report"]["recognized_exercise"]
                 and current.latest["review_revision"] == snapshot["review_revision"]
                 and abs(current_report["timestamp_ms"]-snapshot["action_report"]["timestamp_ms"]) <= 15_000)
        result["status"] = "completed" if fresh else "stale"
        if not fresh or not PerceptionSession.policy(current.latest)["handoff_allowed"]:
            result["perception_agent"]["handoff_allowed"] = False
            result["perception_agent"]["decision"] = "observe"
        if fresh:
            session.review_result = result
            session.review_baseline = snapshot["review_revision"]
            session.review_cached_at = time.monotonic()
            session.summary = {"exercise": current_report["recognized_exercise"],
                               "decision": result["perception_agent"]["decision"],
                               "reason": result["perception_agent"]["reason"],
                               "observation_request": result["perception_agent"]["observation_request"],
                               "reviewed_timestamp_ms": snapshot["action_report"]["timestamp_ms"]}
        # Reviewed evidence is returned as its own snapshot, never applied to new frames.
        return result
    except ConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    except ModelError as exc:
        raise HTTPException(502, str(exc)) from exc
    finally:
        session.reviewing = False

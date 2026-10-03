"""Completed-set analysis and optional historical A/B Agent review."""
import asyncio
from copy import deepcopy
import time
from threading import BoundedSemaphore

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.routes import manager
from app.action_report_adapter import normalize
from app.engine import validate_movement
from app.model_client import ModelError
from app.engine import InputError
from app.routers import run
from perception.agent import PerceptionAgent
from perception.sets import BufferedFrame, analyze_set, buffer_status

router = APIRouter()
_SET_CAPACITY = BoundedSemaphore(2)


@router.get("/agent-a/capture-protocols")
def capture_protocols():
    from perception.views import PROTOCOLS
    return {"version":"exercise_view_v1", "exercises":PROTOCOLS,
            "setup":"固定机位、全身入镜、手脚保留边距、避免遮挡",
            "measurement_limit":"单摄像头推断的深度与关节角度未经外部标定"}


def local_analysis(*args, include_trace=False):
    if not _SET_CAPACITY.acquire(blocking=False):
        raise HTTPException(429, "Set analysis is busy; retry shortly")
    try:
        return imported_analysis(*args, True) if include_trace else analyze_set(*args)
    finally:
        _SET_CAPACITY.release()


class FinishRequest(BaseModel):
    include_agents: bool = False


class SetRequest(FinishRequest):
    session_id: str = Field(min_length=1, max_length=64)
    frames: list[BufferedFrame] = Field(min_length=1, max_length=2400)
    include_trace: bool = False


def imported_analysis(frames, session_id, include_trace):
    result, snapshots = analyze_set(frames, session_id)
    if include_trace:
        started = time.perf_counter()
        from state_machine.manager import FormManager
        from reporting.builder import ActionReportBuilder
        from perception.agent import PerceptionSession
        from perception.pipeline import process_pose_frame
        form, builder, perception = FormManager(), ActionReportBuilder(session_id), PerceptionSession()
        rows = []
        # One immutable replay records the same measured chain used by live input.
        for payload in frames:
            state, report, event, policy, timing = process_pose_frame(form, builder, perception, payload)
            rows.append({"input":payload, "timestamp":payload["timestamp"], "filtered_landmarks":state.filtered_landmarks,
                         "candidate":state.candidate_exercise.value if state.candidate_exercise else None,
                         "source":state.exercise_source, "action_report":report.model_dump(),
                         "urdf_xml":perception.fitter.xml, "policy":policy, "timings_ms":timing})
        result["trace"] = rows
        result["processing"]["diagnostic_replay_ms"] = (time.perf_counter()-started)*1000
    return result, snapshots


def captured_session(client_id):
    for key, (stamp, _) in list(manager.recent_sessions.items()):
        if time.monotonic()-stamp > 900:
            manager.recent_sessions.pop(key, None)
    session = manager.perception_sessions.get(client_id)
    if session is None:
        archived = manager.recent_sessions.get(client_id)
        session = archived[1] if archived else None
    if session is None:
        raise HTTPException(404, "No captured set for this session")
    return session


async def with_agents(result, snapshots):
    result = deepcopy(result)
    started = time.perf_counter()
    if len(result["segments"]) > 8:
        result["agent_error"] = "Too many action segments; split the capture before requesting Agents"
        return result
    for segment, snapshot in zip(result["segments"], snapshots):
        if snapshot is None:
            continue
        if segment.get("analysis"):
            continue
        segment.pop("agent_error", None)
        try:
            reviewed = await asyncio.to_thread(PerceptionAgent().run, snapshot)
            segment["perception_review"] = reviewed
            if not reviewed["perception_agent"]["handoff_allowed"]:
                continue
            movement = normalize({"action_report":reviewed["action_report"]})
            validate_movement(movement)
            segment["analysis"] = await asyncio.to_thread(run, "movement", movement)
        except (ModelError, InputError, HTTPException) as exc:
            segment["agent_error"] = str(exc)
    result.setdefault("processing", {})["agent_review_ms"] = (time.perf_counter()-started)*1000
    return result


@router.get("/agent-a/sessions/{client_id}/set")
def set_status(client_id: str):
    session = captured_session(client_id)
    return {"capture":buffer_status(session), "completed_set":session.completed_set}


@router.post("/agent-a/sessions/{client_id}/finish-set")
async def finish_set(client_id: str, request: FinishRequest):
    session = captured_session(client_id)
    if session.set_busy:
        raise HTTPException(409, "Set processing is already running")
    if not session.frame_buffer:
        raise HTTPException(409, "No new frames; use review-set for the previous result")
    session.set_busy = True
    frames = list(session.frame_buffer)
    dropped, rejected = session.buffer_dropped, session.buffer_rejected
    generation = session.generation
    analyzed = False
    session.frame_buffer.clear()
    session.buffer_dropped = session.buffer_rejected = 0
    try:
        result, snapshots = await asyncio.to_thread(local_analysis, frames, client_id, dropped, rejected)
        analyzed = True
        result["source_reset_during_analysis"] = generation != session.generation
        session.completed_set, session.set_snapshots = result, snapshots
        if request.include_agents:
            result = await with_agents(result, snapshots)
        # The result belongs to an immutable completed set, never to live frames.
        session.completed_set, session.set_snapshots = result, snapshots
        return result
    except Exception:
        if not analyzed and generation == session.generation:
            combined = frames + list(session.frame_buffer)
            session.buffer_dropped += dropped + max(0, len(combined)-session.frame_buffer.maxlen)
            session.buffer_rejected += rejected
            session.frame_buffer.clear()
            session.frame_buffer.extend(combined)
        raise
    finally:
        session.set_busy = False


@router.post("/agent-a/sessions/{client_id}/review-set")
async def review_set(client_id: str, request: FinishRequest):
    session = captured_session(client_id)
    if session.set_busy:
        raise HTTPException(409, "Set processing is already running")
    if not session.completed_set:
        raise HTTPException(409, "Finish a set first")
    if not request.include_agents:
        return session.completed_set
    session.set_busy = True
    try:
        result = await with_agents(session.completed_set, session.set_snapshots)
        session.completed_set = result
        return result
    finally:
        session.set_busy = False


@router.post("/agent-a/analyze-set")
async def analyze_imported_set(request: SetRequest):
    frames = [frame.model_dump(exclude_none=True) for frame in request.frames]
    result, snapshots = await asyncio.to_thread(local_analysis, frames, request.session_id, include_trace=request.include_trace)
    return await with_agents(result, snapshots) if request.include_agents else result

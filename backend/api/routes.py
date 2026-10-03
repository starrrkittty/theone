"""WebSocket API for real-time exercise form correction."""

import logging
import re
import time
import math
import json
from collections import OrderedDict
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from config.settings import settings
from exercises.registry import supported_exercises_payload
from reporting.builder import ActionReportBuilder
from schemas.action_report import ActionReport, RecognitionEvent
from state_machine.manager import FormManager, SystemState
from perception.agent import PerceptionSession
from perception.pipeline import process_pose_frame
from perception.sets import capture_frame, buffer_status


router = APIRouter()
logger = logging.getLogger(__name__)
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
_CAMERA_VIEW_CHOICES = {"auto", "front", "side", "three_quarter"}


class FormCorrectionResponse(BaseModel):
    """Response sent back to client."""
    state: str  # "idle" | "stationary" | "scanning" | "active"
    current_exercise: Optional[str]
    exercise_display: str
    rep_count: int
    rep_phase: str  # "idle" | "setup" | "eccentric" | "concentric" | "hold"
    phase_display: str  # Human-readable per-exercise (e.g. "Lowering down")
    is_rep_valid: bool
    violations: list[str]
    corrections: list[str]
    correction_message: str
    joint_colors: dict[str, str]
    confidence: float  # Legacy alias of form_confidence
    is_stationary: bool
    timestamp: float
    exercise_confidence: float = 0.0
    form_confidence: float = 0.0
    signal_quality: str = "good"
    exercise_variant: Optional[str] = None
    exercise_source: str = "hmm"
    camera_view: str = "unknown"
    hold_seconds: float = 0.0
    recognition_event: Optional[RecognitionEvent] = None
    action_report: ActionReport
    perception_agent: dict = Field(default_factory=dict)
    processing: dict = Field(default_factory=dict)
    capture: dict = Field(default_factory=dict)


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.form_managers: dict[str, FormManager] = {}
        self.report_builders: dict[str, ActionReportBuilder] = {}
        self._last_frame_times: dict[str, float] = {}
        self.perception_sessions: dict[str, PerceptionSession] = {}
        self.recent_sessions = OrderedDict()

    async def connect(self, websocket: WebSocket, client_id: str) -> bool:
        if client_id in self.active_connections:
            await websocket.close(code=1008, reason="Session ID already connected")
            return False
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self.form_managers[client_id] = FormManager()
        self.report_builders[client_id] = ActionReportBuilder(client_id)
        self._last_frame_times[client_id] = 0.0
        self.perception_sessions[client_id] = PerceptionSession()
        self.recent_sessions.pop(client_id, None)
        return True

    def disconnect(self, client_id: str, websocket=None) -> None:
        if websocket is not None and self.active_connections.get(client_id) is not websocket:
            return
        self.active_connections.pop(client_id, None)
        self.form_managers.pop(client_id, None)
        self.report_builders.pop(client_id, None)
        self._last_frame_times.pop(client_id, None)
        session = self.perception_sessions.pop(client_id, None)
        if session:
            self.recent_sessions[client_id] = (time.monotonic(), session)
            while len(self.recent_sessions) > 8:
                self.recent_sessions.popitem(last=False)

    def get_manager(self, client_id: str) -> Optional[FormManager]:
        return self.form_managers.get(client_id)

    def get_report_builder(self, client_id: str) -> Optional[ActionReportBuilder]:
        return self.report_builders.get(client_id)

    def should_rate_limit(self, client_id: str, max_fps: Optional[int] = None) -> bool:
        """Return True if this frame should be dropped (rate limit exceeded)."""
        max_fps = max_fps or settings.MAX_FRAMES_PER_SECOND
        now = time.monotonic()
        last = self._last_frame_times.get(client_id, 0.0)
        if (now - last) < (1.0 / max_fps):
            return True
        self._last_frame_times[client_id] = now
        return False

    async def send_response(self, client_id: str, response: FormCorrectionResponse, compact: bool = False) -> None:
        websocket = self.active_connections.get(client_id)
        if websocket:
            started = time.perf_counter()
            payload = response.model_dump()
            if compact:
                kin = payload["action_report"].get("kinematics", {})
                for key in ("structure", "fit", "model_id", "fk_endpoint_residuals", "tracking_observations"):
                    kin.pop(key, None)
                payload["action_report"]["transport"] = "compact_live; fetch session snapshot for full structure"
            payload["processing"]["projection_ms"] = (time.perf_counter()-started)*1000
            await websocket.send_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False))


manager = ConnectionManager()


@router.websocket("/ws/pose/{client_id}")
async def pose_websocket(websocket: WebSocket, client_id: str):
    if (
        len(client_id) > settings.MAX_CLIENT_ID_LENGTH
        or not _CLIENT_ID_RE.fullmatch(client_id)
    ):
        await websocket.close(code=1008, reason="Invalid client_id")
        return

    if not await manager.connect(websocket, client_id):
        return
    form_manager = manager.get_manager(client_id)
    report_builder = manager.get_report_builder(client_id)

    try:
        while True:
            data = await websocket.receive_json()
            if not isinstance(data, dict):
                await websocket.send_json({"error":"Pose payload must be an object"})
                continue

            # Rate limit: drop excess frames silently
            if manager.should_rate_limit(client_id):
                continue

            landmarks = data.get("landmarks", [])
            timestamp = data.get("timestamp", time.time() * 1000)
            if type(timestamp) not in {int,float} or not math.isfinite(timestamp) or timestamp <= 0:
                await websocket.send_json({"error":"timestamp must be a positive finite number"})
                continue

            state, report, recognition_event, perception_agent, timings = process_pose_frame(
                form_manager, report_builder, manager.perception_sessions[client_id], data)
            capture_frame(manager.perception_sessions[client_id], {**data, "timestamp":timestamp})
            camera_view = report.camera_view
            result = state.exercise_result
            response = FormCorrectionResponse(
                state=state.system_state.value,
                current_exercise=state.current_exercise.value if state.current_exercise else None,
                exercise_display=form_manager.get_state_display() if state.current_exercise else "等待可靠的动作证据...",
                rep_count=result.rep_count if result else 0,
                rep_phase=result.rep_phase if result else "idle",
                phase_display=result.phase_display if result else "",
                is_rep_valid=result.is_valid if result else False,
                violations=result.violations if result else [],
                corrections=result.corrections if result else [],
                correction_message=_build_correction_message(result),
                joint_colors=result.joint_colors if result else {},
                confidence=state.form_confidence,
                is_stationary=state.is_stationary,
                timestamp=timestamp,
                exercise_confidence=state.exercise_confidence,
                form_confidence=state.form_confidence,
                signal_quality=state.signal_quality,
                exercise_variant=state.exercise_variant,
                exercise_source=state.exercise_source,
                camera_view=camera_view,
                hold_seconds=float(getattr(result, "hold_seconds", 0.0)) if result else 0.0,
                recognition_event=recognition_event,
                action_report=report,
                perception_agent=perception_agent,
                processing=timings,
                capture=buffer_status(manager.perception_sessions[client_id]),
            )

            await manager.send_response(client_id, response, data.get("response_mode") == "compact")

    except WebSocketDisconnect:
        manager.disconnect(client_id, websocket)
    except Exception:
        logger.exception("WebSocket error for client_id=%s", client_id)
        manager.disconnect(client_id, websocket)
        await websocket.close(code=1011, reason="Pose processing failed; reconnect or reset session")


def _build_correction_message(result) -> str:
    if not result:
        return ""
    if not result.corrections:
        if result.is_valid:
            return "未触发当前规则的提示；不代表完整动作正确。"
        return ""
    return result.corrections[0] if result.corrections else ""


def _resolve_camera_view(requested_view, estimated_view: str) -> str:
    if isinstance(requested_view, str):
        normalized = requested_view.strip().lower()
        if normalized in _CAMERA_VIEW_CHOICES and normalized != "auto":
            return normalized
    return estimated_view or "unknown"


@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "connections": len(manager.active_connections),
        "supported_exercises": supported_exercises_payload(),
    }


@router.get("/exercises")
async def list_supported_exercises():
    """List exercise labels currently supported by the detection pipeline."""
    return {"exercises": supported_exercises_payload()}


@router.post("/reset/{client_id}")
async def reset_session(client_id: str):
    form_manager = manager.get_manager(client_id)
    if form_manager:
        form_manager.reset()
        report_builder = manager.get_report_builder(client_id)
        if report_builder:
            report_builder.reset()
        perception = manager.perception_sessions.get(client_id)
        if perception:
            perception.reset()
        return {"status": "reset", "client_id": client_id}
    return {"status": "not_found", "client_id": client_id}

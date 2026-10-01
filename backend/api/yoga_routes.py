"""WebSocket + REST API for the yoga (static held pose) mode.

Kept in its own router/connection-manager, separate from ``api/routes.py``, so
the classifier-driven exercise pipeline and the explicit-selection yoga pipeline
stay isolated. The client sends the target pose with every frame; the frontend
guided-flow controller changes that field to advance through a sequence.
"""

import logging
import re
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from config.settings import settings
from exercises.yoga_registry import supported_yoga_payload
from state_machine.yoga_manager import YogaFrameState, YogaManager


router = APIRouter()
logger = logging.getLogger(__name__)
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")


class YogaPoseResponse(BaseModel):
    """Per-frame response sent back to the yoga client."""
    state: str  # "idle" | "adjusting" | "holding"
    current_pose: Optional[str]
    pose_display: str
    camera_view: str
    is_in_pose: bool
    hold_seconds: float
    hold_target_seconds: float
    hold_progress: float       # 0..1
    hold_complete: bool
    just_completed: bool
    violations: list[str]
    corrections: list[str]
    correction_message: str
    joint_colors: dict[str, str]
    confidence: float
    timestamp: float


class YogaConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.yoga_managers: dict[str, YogaManager] = {}

    async def connect(self, websocket: WebSocket, client_id: str) -> None:
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self.yoga_managers[client_id] = YogaManager()

    def disconnect(self, client_id: str) -> None:
        self.active_connections.pop(client_id, None)
        self.yoga_managers.pop(client_id, None)

    def get_manager(self, client_id: str) -> Optional[YogaManager]:
        return self.yoga_managers.get(client_id)

    async def send_response(self, client_id: str, response: YogaPoseResponse) -> None:
        websocket = self.active_connections.get(client_id)
        if websocket:
            await websocket.send_json(response.model_dump())


manager = YogaConnectionManager()


def _correction_message(state: YogaFrameState) -> str:
    if state.current_pose is None:
        return "Select a pose to begin"
    if state.hold_complete:
        return "Great hold — pose complete!"
    if not state.is_in_pose:
        return state.corrections[0] if state.corrections else "Move into the pose"
    return "Hold steady — breathe"


def _unknown_pose_response(pose: str, timestamp: float) -> YogaPoseResponse:
    """Reply for a frame naming a pose the detector does not implement.

    Without this the manager would keep reporting ``idle`` forever and a client
    with a typo'd label would have no way to tell that from "no pose selected".
    The echoed label is truncated so a client cannot bloat the response.
    """
    label = pose[:40]
    return YogaPoseResponse(
        state="idle",
        current_pose=None,
        pose_display="",
        camera_view="front",
        is_in_pose=False,
        hold_seconds=0.0,
        hold_target_seconds=0.0,
        hold_progress=0.0,
        hold_complete=False,
        just_completed=False,
        violations=[f"Unknown pose '{label}'"],
        corrections=["Choose a pose label listed by GET /api/yoga/poses"],
        correction_message=f"Unknown pose '{label}'",
        joint_colors={},
        confidence=0.0,
        timestamp=timestamp,
    )


def _build_response(state: YogaFrameState, timestamp: float) -> YogaPoseResponse:
    return YogaPoseResponse(
        state=state.state,
        current_pose=state.current_pose,
        pose_display=state.pose_display,
        camera_view=state.camera_view,
        is_in_pose=state.is_in_pose,
        hold_seconds=state.hold_seconds,
        hold_target_seconds=state.hold_target_seconds,
        hold_progress=state.hold_progress,
        hold_complete=state.hold_complete,
        just_completed=state.just_completed,
        violations=state.violations,
        corrections=state.corrections,
        correction_message=_correction_message(state),
        joint_colors=state.joint_colors,
        confidence=state.confidence,
        timestamp=timestamp,
    )


@router.websocket("/ws/yoga/{client_id}")
async def yoga_websocket(websocket: WebSocket, client_id: str):
    if (
        len(client_id) > settings.MAX_CLIENT_ID_LENGTH
        or not _CLIENT_ID_RE.fullmatch(client_id)
    ):
        await websocket.close(code=1008, reason="Invalid client_id")
        return

    await manager.connect(websocket, client_id)
    yoga_manager = manager.get_manager(client_id)

    try:
        while True:
            data = await websocket.receive_json()

            if not data.get("landmarks"):
                continue

            landmarks = data["landmarks"]
            timestamp = data.get("timestamp", 0)

            # Switch/lock the target pose when the client specifies one. The
            # yoga client is low-frequency (the browser throttles to ~10-15fps)
            # so every frame is processed — no rate-limit dropping needed here.
            pose = data.get("pose")
            if isinstance(pose, str) and pose:
                if not yoga_manager.set_pose(pose):
                    await manager.send_response(
                        client_id, _unknown_pose_response(pose, timestamp)
                    )
                    continue

            state = yoga_manager.process_frame(landmarks)
            await manager.send_response(client_id, _build_response(state, timestamp))

    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception:
        logger.exception("Yoga WebSocket error for client_id=%s", client_id)
        manager.disconnect(client_id)


@router.get("/yoga/poses")
async def list_yoga_poses():
    """List the static yoga poses supported by the detector."""
    return {"poses": supported_yoga_payload()}


@router.get("/yoga/health")
async def yoga_health():
    """Yoga-scoped health probe.

    A yoga-only client should poll this rather than ``/api/health``: it reports
    the yoga connection count and pose contract without pulling in the
    exercise-classifier metadata. Also serves as the cold-start warm-up ping on
    Render's free tier.
    """
    return {
        "status": "healthy",
        "connections": len(manager.active_connections),
        "supported_poses": supported_yoga_payload(),
    }


@router.post("/reset/yoga/{client_id}")
async def reset_yoga_session(client_id: str):
    yoga_manager = manager.get_manager(client_id)
    if yoga_manager:
        yoga_manager.reset()
        return {"status": "reset", "client_id": client_id}
    return {"status": "not_found", "client_id": client_id}

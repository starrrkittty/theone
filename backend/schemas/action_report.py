"""Versioned output contract produced by Agent A.

The language/planning agent must consume this compact report instead of raw
MediaPipe landmarks or URDF XML.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class CandidateExercise(BaseModel):
    exercise: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: str


class ViolationItem(BaseModel):
    type: str
    message: str
    severity: Literal["low", "medium", "high"] = "medium"
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    joints: list[str] = Field(default_factory=list)
    correction: str = ""
    consecutive_frames: int = 1


class ActionMetrics(BaseModel):
    joint_angles: dict[str, float] = Field(default_factory=dict)
    hold_seconds: float = Field(default=0.0, ge=0.0)
    rep_quality: Optional[float] = None
    partial_reps: int = Field(default=0, ge=0)


class AgentContext(BaseModel):
    should_coach_now: bool = False
    priority: Literal["none", "encouragement", "form_correction", "safety"] = "none"
    recommended_intent: str = "observe"
    repeated_error_count: int = Field(default=0, ge=0)
    possible_fatigue: bool = False


class RecognitionDetails(BaseModel):
    exercise_id: str = "unknown"
    display_name: str = ""
    category: str = "other"
    source: str = "none"
    uncertainty_reason: Optional[str] = None


class RoutingDetails(BaseModel):
    mode: Literal["verified_specialist", "general_coaching", "observe_more"] = "observe_more"
    specialist: Optional[str] = None
    fallback_specialist: Optional[str] = None


class ActionCapabilities(BaseModel):
    semantic_recognition: bool = False
    precise_rep_count: bool = False
    specialized_form_correction: bool = False
    hold_timing: bool = False
    general_guidance: bool = False


class ActionReport(BaseModel):
    schema_version: Literal["v2"] = "v2"
    session_id: str
    timestamp_ms: float
    recognition_status: Literal["unknown", "candidate", "confirmed"]
    recognized_exercise: str = "unknown"
    recognition_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    candidate_exercises: list[CandidateExercise] = Field(default_factory=list)
    specialist: Optional[str] = None
    phase: str = "idle"
    repetition: int = Field(default=0, ge=0)
    pose_quality: Literal["good", "acceptable", "unreliable"] = "unreliable"
    camera_view: str = "unknown"
    metrics: ActionMetrics = Field(default_factory=ActionMetrics)
    violations: list[ViolationItem] = Field(default_factory=list)
    agent_context: AgentContext = Field(default_factory=AgentContext)
    recognition: RecognitionDetails = Field(default_factory=RecognitionDetails)
    routing: RoutingDetails = Field(default_factory=RoutingDetails)
    capabilities: ActionCapabilities = Field(default_factory=ActionCapabilities)


class RecognitionEvent(BaseModel):
    event: Literal["exercise_confirmed", "exercise_switched"]
    session_id: str
    timestamp_ms: float
    exercise: str
    confidence: float = Field(ge=0.0, le=1.0)
    specialist: str
    message: str
    route_mode: Literal["verified_specialist", "general_coaching"] = "verified_specialist"

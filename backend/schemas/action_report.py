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
    joint_confidences: dict[str, float] = Field(default_factory=dict)
    confidence_method: str = "missing"
    hold_seconds: float = Field(default=0.0, ge=0.0)
    rep_quality: Optional[float] = None
    partial_reps: int = Field(default=0, ge=0)


class AgentContext(BaseModel):
    should_coach_now: bool = False
    priority: Literal["none", "encouragement", "form_correction", "safety"] = "none"
    recommended_intent: str = "observe"
    repeated_error_count: int = Field(default=0, ge=0)
    possible_fatigue: bool = False


class ActionReport(BaseModel):
    schema_version: Literal["v1"] = "v1"
    session_id: str
    timestamp_ms: float = Field(gt=0, allow_inf_nan=False)
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
    kinematics: dict = Field(default_factory=dict)
    perception_agent: dict = Field(default_factory=dict)


class RecognitionEvent(BaseModel):
    event: Literal["exercise_confirmed", "exercise_switched"]
    session_id: str
    timestamp_ms: float
    exercise: str
    confidence: float = Field(ge=0.0, le=1.0)
    specialist: str
    message: str

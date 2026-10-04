from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class JointObservation(BaseModel):
    angle_deg: float = Field(ge=0, le=360)
    confidence: float = Field(default=1.0, ge=0, le=1)


class MovementInput(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    user_id: str | None = None
    session_id: str
    timestamp: datetime
    exercise_id: str
    rep_index: int = Field(ge=0)
    phase: Literal["descent", "bottom", "ascent", "hold", "unknown"] = "unknown"
    joints: dict[str, JointObservation]
    reported_symptoms: list[str] = Field(default_factory=list)
    metadata: dict[str, str | float | int | bool] = Field(default_factory=dict)


class Finding(BaseModel):
    code: str
    severity: Literal["info", "caution", "stop"]
    joint: str | None = None
    observed: float | str | None = None
    expected: str
    confidence: float = Field(ge=0, le=1)
    source_ids: list[str] = Field(default_factory=list)


class CoachCue(BaseModel):
    priority: int = Field(ge=1, le=5)
    text: str
    rationale: str


class MovementAnalysis(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    session_id: str
    rep_index: int
    exercise_id: str
    routed_to: list[str]
    status: Literal["assessed", "limited", "stop"]
    overall_score: int | None = Field(default=None, ge=0, le=100)
    findings: list[Finding]
    cues: list[CoachCue]
    safety_messages: list[str]
    limitations: list[str]
    missing_observations: list[str] = Field(default_factory=list)


class WorkoutSet(BaseModel):
    exercise_id: str
    reps: int = Field(ge=0)
    target_reps: int | None = Field(default=None, ge=0)
    perceived_effort: int | None = Field(default=None, ge=1, le=10)
    notes: list[str] = Field(default_factory=list)


class WorkoutSummaryRequest(BaseModel):
    user_id: str | None = None
    started_at: datetime
    ended_at: datetime
    sets: list[WorkoutSet]
    user_feedback: list[str] = Field(default_factory=list)
    recovery_check: Literal["good", "usual", "poor", "pain", "not_provided"] = "not_provided"
    reported_symptoms: list[str] = Field(default_factory=list)
    movement_observations: list[dict[str, str | int | float | bool]] = Field(default_factory=list)


class PhasePlanRequest(BaseModel):
    goal: Literal["general_fitness", "strength", "fat_loss", "mobility", "endurance"]
    experience: Literal["beginner", "intermediate", "advanced"] = "beginner"
    days_per_week: int = Field(ge=1, le=7)
    minutes_per_session: int = Field(ge=10, le=180)
    equipment: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class NutritionRequest(BaseModel):
    goal: Literal["general_fitness", "strength", "fat_loss", "endurance"]
    dietary_preferences: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    medical_conditions: list[str] = Field(default_factory=list)

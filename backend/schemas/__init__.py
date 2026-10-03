"""Stable integration contracts shared by Agent A, Agent B, and the app."""

from .action_report import (
    ActionMetrics,
    ActionReport,
    AgentContext,
    CandidateExercise,
    RecognitionEvent,
    ViolationItem,
)

__all__ = [
    "ActionMetrics",
    "ActionReport",
    "AgentContext",
    "CandidateExercise",
    "RecognitionEvent",
    "ViolationItem",
]

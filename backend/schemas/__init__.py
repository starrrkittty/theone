"""Stable integration contracts shared by Agent A, Agent B, and the app."""

from .action_report import (
    ActionCapabilities,
    ActionMetrics,
    ActionReport,
    AgentContext,
    CandidateExercise,
    RecognitionDetails,
    RecognitionEvent,
    RoutingDetails,
    ViolationItem,
)

__all__ = [
    "ActionCapabilities",
    "ActionMetrics",
    "ActionReport",
    "AgentContext",
    "CandidateExercise",
    "RecognitionDetails",
    "RecognitionEvent",
    "RoutingDetails",
    "ViolationItem",
]

"""Capability-aware routing from recognized exercise to Agent B expert."""

from dataclasses import dataclass
from typing import Literal, Optional

from exercises.catalog import ExerciseProfile, semantic_profile


RouteMode = Literal[
    "verified_specialist",
    "general_coaching",
    "observe_more",
]


@dataclass(frozen=True)
class RoutingDecision:
    mode: RouteMode
    specialist: Optional[str]
    fallback_specialist: Optional[str]
    profile: Optional[ExerciseProfile]


def route_exercise(
    exercise_id: str,
    *,
    display_name: Optional[str] = None,
    category: str = "other",
) -> RoutingDecision:
    if exercise_id == "unknown" or not exercise_id:
        return RoutingDecision("observe_more", None, None, None)
    profile = semantic_profile(
        exercise_id,
        display_name=display_name,
        category=category,
    )
    if profile is None:
        return RoutingDecision("observe_more", None, None, None)
    if profile.specialist:
        return RoutingDecision(
            "verified_specialist",
            profile.specialist,
            profile.fallback_specialist,
            profile,
        )
    return RoutingDecision(
        "general_coaching",
        profile.fallback_specialist,
        profile.fallback_specialist,
        profile,
    )


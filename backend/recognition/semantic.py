"""Validation and temporal confirmation for open-vocabulary recognition."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping, Optional

from exercises.catalog import ExerciseProfile, get_exercise_profile, semantic_profile


LOCAL_STGCN_MODEL_ID = "mmfit-mediapipe-semantic-v1"
CANDIDATE_STGCN_MODEL_ID = "mmfit-haa500-semantic-pose-families-v9"


# Calibrated on MM-Fit participant p06 after product-domain MediaPipe
# extraction.  Participant p08 remains the held-out check.  Core labels are
# excluded below and continue to require geometric/state-machine confirmation.
LOCAL_STGCN_THRESHOLDS = {
    "dumbbell_row": 0.75,
    "jumping_jack": 0.72,
    "lateral_raise": 0.995,
    "lunge": 0.97,
    "shoulder_press": 0.72,
    "situp": 0.999,
    "tricep_extension": 0.99,
}


# Candidate thresholds were selected on the v9 validation split with unknown
# rejection enabled.  The candidate stays opt-in until it passes the real-video
# acceptance gate; keeping thresholds keyed by model prevents a client from
# loading one model while claiming the calibration of another.
CANDIDATE_STGCN_THRESHOLDS = {
    "dumbbell_row": 0.72,
    "jumping_jack": 0.72,
    "lateral_raise": 0.72,
    "lunge": 0.72,
    "shoulder_press": 0.72,
    "situp": 0.72,
    "tricep_extension": 0.83,
    "burpee": 0.72,
    "jump_rope": 0.72,
    "pullup": 0.92,
    "running_in_place": 0.72,
    "yoga_tree": 0.72,
    "yoga_triangle": 0.72,
}


LOCAL_STGCN_THRESHOLDS_BY_MODEL = {
    LOCAL_STGCN_MODEL_ID: LOCAL_STGCN_THRESHOLDS,
    CANDIDATE_STGCN_MODEL_ID: CANDIDATE_STGCN_THRESHOLDS,
}


def is_supported_local_model(model_id: object) -> bool:
    return isinstance(model_id, str) and model_id in LOCAL_STGCN_THRESHOLDS_BY_MODEL


@dataclass(frozen=True)
class SemanticEvidence:
    profile: ExerciseProfile
    confidence: float
    source: str


@dataclass(frozen=True)
class SemanticState:
    profile: ExerciseProfile
    confidence: float
    source: str
    confirmed: bool


def parse_semantic_result(raw: object) -> Optional[SemanticEvidence]:
    """Parse an untrusted Video LLM/open-vocabulary JSON result."""
    if not isinstance(raw, Mapping):
        return None
    raw_id = raw.get("exercise_id", raw.get("exercise", raw.get("label")))
    if not isinstance(raw_id, str):
        return None
    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        return None
    if not isfinite(confidence):
        return None
    display_name = raw.get("display_name", raw.get("display_name_zh"))
    if display_name is not None and not isinstance(display_name, str):
        return None
    category = raw.get("category", "other")
    if not isinstance(category, str):
        category = "other"
    source = raw.get("source", "video_semantic")
    if not isinstance(source, str) or not source.strip():
        source = "video_semantic"
    profile = semantic_profile(
        raw_id,
        display_name=display_name,
        category=category,
    )
    if profile is None:
        return None
    return SemanticEvidence(
        profile=profile,
        confidence=max(0.0, min(1.0, confidence)),
        source=source.strip()[:40],
    )


def parse_semantic_probabilities(
    raw: object,
    model_id: str = LOCAL_STGCN_MODEL_ID,
) -> Optional[SemanticEvidence]:
    """Take the strongest catalogued long-tail class from a local model.

    Verified core labels are intentionally ignored here; they must still pass
    the geometric/state-machine guards before gaining specialist capabilities.
    """
    thresholds = LOCAL_STGCN_THRESHOLDS_BY_MODEL.get(model_id)
    if thresholds is None or not isinstance(raw, Mapping):
        return None
    candidates: list[tuple[float, ExerciseProfile]] = []
    for raw_label, raw_score in raw.items():
        if not isinstance(raw_label, str):
            continue
        profile = get_exercise_profile(raw_label)
        if profile is None or profile.specialist is not None:
            continue
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            continue
        if isfinite(score):
            candidates.append((max(0.0, min(1.0, score)), profile))
    if not candidates:
        return None
    confidence, profile = max(candidates, key=lambda item: item[0])
    required_confidence = thresholds.get(profile.id, 1.0)
    if confidence < required_confidence:
        return None
    return SemanticEvidence(profile=profile, confidence=confidence, source="local_stgcn")


class SemanticRecognitionTracker:
    """Require repeated semantic observations before announcing an action."""

    def __init__(
        self,
        *,
        confirmation_hits: int = 2,
        min_confidence: float = 0.72,
        stale_after_ms: float = 8000.0,
    ):
        self.confirmation_hits = confirmation_hits
        self.min_confidence = min_confidence
        self.stale_after_ms = stale_after_ms
        self.reset()

    def reset(self) -> None:
        self._candidate_id: Optional[str] = None
        self._hits = 0
        self._confirmed: Optional[SemanticState] = None
        self._last_timestamp_ms = 0.0

    def update(
        self,
        evidence: Optional[SemanticEvidence],
        timestamp_ms: float,
        *,
        core_confirmed: bool,
    ) -> Optional[SemanticState]:
        if core_confirmed:
            self.reset()
            return None
        if (
            self._last_timestamp_ms
            and timestamp_ms - self._last_timestamp_ms > self.stale_after_ms
        ):
            self.reset()
        if evidence is None:
            return self._confirmed
        self._last_timestamp_ms = timestamp_ms
        if evidence.confidence < self.min_confidence:
            return self._confirmed
        if evidence.profile.id != self._candidate_id:
            self._candidate_id = evidence.profile.id
            self._hits = 1
        else:
            self._hits += 1
        state = SemanticState(
            profile=evidence.profile,
            confidence=evidence.confidence,
            source=evidence.source,
            confirmed=self._hits >= self.confirmation_hits,
        )
        if state.confirmed:
            self._confirmed = state
        return self._confirmed or state


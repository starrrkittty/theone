"""Validate probabilities produced by an optional client or video model.

The current browser ST-GCN and a future local ActionCLIP service can both use
this contract. Untrusted labels and malformed scores are ignored.
"""

from dataclasses import dataclass
from math import isfinite
from typing import Mapping, Optional


_ALIASES = {
    "push_up": "pushup",
    "push-up": "pushup",
    "bicep-curl": "bicep_curl",
    "alternate-bicep-curl": "alternate_bicep_curl",
    "not_exercising": "unknown",
    "idle": "unknown",
    "curl-stand": "bicep_curl",
    "curl-seat": "bicep_curl",
    "alt-stand": "alternate_bicep_curl",
    "alt-seat": "alternate_bicep_curl",
}

_ALLOWED = {
    "squat",
    "pushup",
    "plank",
    "bicep_curl",
    "alternate_bicep_curl",
    "unknown",
}


@dataclass(frozen=True)
class ExternalEvidence:
    top1: str
    top1_confidence: float
    top2: Optional[str]
    top2_confidence: float

    @property
    def margin(self) -> float:
        return self.top1_confidence - self.top2_confidence


def parse_external_probabilities(
    raw: object,
) -> Optional[ExternalEvidence]:
    if not isinstance(raw, Mapping):
        return None

    cleaned: dict[str, float] = {}
    for raw_label, raw_score in raw.items():
        if not isinstance(raw_label, str):
            continue
        label = _ALIASES.get(raw_label.strip().lower(), raw_label.strip().lower())
        if label not in _ALLOWED:
            continue
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            continue
        if not isfinite(score):
            continue
        if isinstance(raw_score, bool) or not 0.0 <= score <= 1.0:
            continue
        cleaned[label] = min(1.0, cleaned.get(label, 0.0) + score)

    if not cleaned:
        return None
    ranked = sorted(cleaned.items(), key=lambda item: item[1], reverse=True)
    top1, top1_score = ranked[0]
    if len(ranked) > 1:
        top2, top2_score = ranked[1]
    else:
        top2, top2_score = None, 0.0
    return ExternalEvidence(top1, top1_score, top2, top2_score)

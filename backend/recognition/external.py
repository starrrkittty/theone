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
    # The bundled browser ST-GCN was trained for curl variants.  Map its
    # original labels into the stable Agent-A exercise vocabulary.
    "curl-stand": "bicep_curl",
    "curl-seat": "bicep_curl",
    "alt-stand": "alternate_bicep_curl",
    "alt-seat": "alternate_bicep_curl",
}

_CURL_VARIANT_LABELS = {
    "curl-stand",
    "curl-seat",
    "alt-stand",
    "alt-seat",
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
    scope: str = "general"
    raw_top1: str = ""

    @property
    def margin(self) -> float:
        return self.top1_confidence - self.top2_confidence


def parse_external_probabilities(
    raw: object,
) -> Optional[ExternalEvidence]:
    if not isinstance(raw, Mapping):
        return None

    cleaned: dict[str, float] = {}
    raw_winners: dict[str, str] = {}
    accepted_raw_labels: set[str] = set()
    for raw_label, raw_score in raw.items():
        if not isinstance(raw_label, str):
            continue
        normalized_raw = raw_label.strip().lower()
        label = _ALIASES.get(normalized_raw, normalized_raw)
        if label not in _ALLOWED:
            continue
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            continue
        if not isfinite(score):
            continue
        accepted_raw_labels.add(normalized_raw)
        clipped = max(0.0, min(1.0, score))
        if clipped >= cleaned.get(label, -1.0):
            cleaned[label] = clipped
            raw_winners[label] = normalized_raw

    if not cleaned:
        return None
    ranked = sorted(cleaned.items(), key=lambda item: item[1], reverse=True)
    top1, top1_score = ranked[0]
    if len(ranked) > 1:
        top2, top2_score = ranked[1]
    else:
        top2, top2_score = None, 0.0
    scope = (
        "curl_only"
        if accepted_raw_labels and accepted_raw_labels <= _CURL_VARIANT_LABELS
        else "general"
    )
    return ExternalEvidence(
        top1,
        top1_score,
        top2,
        top2_score,
        scope=scope,
        raw_top1=raw_winners.get(top1, top1),
    )

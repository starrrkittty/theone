"""Other supported action fixtures; synthetic contract coverage, not accuracy."""
import importlib.util
from pathlib import Path

import pytest

from perception.sets import analyze_set
from perception.evidence import evidence_packet
from perception.agent import PerceptionSession

path = Path(__file__).resolve().parents[2]/"tools"/"make_synthetic_cases.py"
spec = importlib.util.spec_from_file_location("synthetic_other_actions", path)
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


@pytest.mark.parametrize("case_id", ["moving_curl", "alternating_curl", "moving_pushup", "forearm_plank"])
def test_other_supported_completed_sets(case_id):
    clip = next(item for item in fixtures.cases() if item["id"] == case_id)
    frames = [{**frame, "timestamp":1700000000000+frame["timestamp_ms"]} for frame in clip["frames"]]
    result, snapshots = analyze_set(frames, case_id)
    assert len(result["segments"]) == 1
    segment = result["segments"][0]
    label = clip["expected_exercise"]
    assert segment["exercise"] == label
    assert segment["repetitions"] == clip["reference_repetitions"][label]
    assert segment["agent_eligible"]
    if clip["reference_hold_seconds"] is not None:
        assert segment["hold_seconds"] == pytest.approx(clip["reference_hold_seconds"], abs=.01)
    packet = evidence_packet(snapshots[0], PerceptionSession.policy(snapshots[0]))
    assert packet["completed_set"]["repetitions"] == segment["repetitions"]


@pytest.mark.parametrize("case_id", ["static_pushup_bottom", "static_standing", "static_bent_arms"])
def test_static_negative_completed_sets(case_id):
    clip = next(item for item in fixtures.cases() if item["id"] == case_id)
    result, _ = analyze_set([{**frame, "timestamp":1700000000000+frame["timestamp_ms"]} for frame in clip["frames"]], case_id)
    assert result["status"] == "awaiting_evidence"
    assert result["segments"] == []

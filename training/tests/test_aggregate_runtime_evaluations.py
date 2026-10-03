from __future__ import annotations

import json
from pathlib import Path

import pytest

from training.aggregate_runtime_evaluations import aggregate, load_export


def _payload(expected: str, predicted: str, participant: str, clip: str) -> dict:
    event = None if predicted == "unknown" else "exercise_confirmed"
    return {
        "schema_version": "agent-a-runtime-evaluation/v1",
        "clip": {
            "participant_id": participant,
            "clip_id": clip,
            "expected_exercise": expected,
            "source_type": "live_video_call",
            "camera_view": "front",
            "lighting": "normal",
            "occlusion": "none",
            "multi_person": False,
        },
        "model": {
            "client_model_id": "test-model",
            "action_report_schema": "v2",
        },
        "telemetry": {
            "frames": 20,
            "unreliableFrames": 1,
            "exerciseSwitches": 0,
            "trace": [{
                "recognizedExercise": predicted,
                "recognitionEvent": event,
            }],
        },
        "summary": {"firstConfirmedLatencyMs": None if predicted == "unknown" else 1500},
        "recognition_history": [],
        "latest_action_report": None,
    }


def _aggregate(rows: list[dict], **overrides) -> dict:
    settings = {
        "required_labels": ["squat", "unknown"],
        "min_participants": 1,
        "min_clips": 2,
        "min_clips_per_label": 1,
        "min_accuracy": 0.8,
        "min_known_recall": 0.7,
        "max_unknown_false_accept": 0.1,
        "max_median_latency_ms": 4000,
        "max_p90_latency_ms": 6000,
        "max_switch_clip_rate": 0.1,
        "max_unreliable_rate": 0.3,
    }
    settings.update(overrides)
    return aggregate(rows, **settings)


def test_load_export_uses_confirmed_event_as_clip_prediction(tmp_path: Path) -> None:
    path = tmp_path / "agent-a-evaluation-one.json"
    path.write_text(
        json.dumps(_payload("squat", "squat", "p01", "clip01")),
        encoding="utf-8",
    )

    row = load_export(path)

    assert row["predicted"] == "squat"
    assert row["correct"] is True


def test_gate_passes_clean_known_and_unknown_clips(tmp_path: Path) -> None:
    rows = []
    for expected, predicted, clip in (
        ("squat", "squat", "known"),
        ("unknown", "unknown", "negative"),
    ):
        path = tmp_path / f"agent-a-evaluation-{clip}.json"
        path.write_text(
            json.dumps(_payload(expected, predicted, "p01", clip)),
            encoding="utf-8",
        )
        rows.append(load_export(path))

    report = _aggregate(rows)

    assert report["passed"] is True
    assert report["metrics"]["clip_accuracy"] == 1.0
    assert report["metrics"]["unknown_false_accept_rate"] == 0.0


def test_gate_rejects_unknown_false_accept(tmp_path: Path) -> None:
    rows = []
    for expected, predicted, clip in (
        ("squat", "squat", "known"),
        ("unknown", "pushup", "negative"),
    ):
        path = tmp_path / f"agent-a-evaluation-{clip}.json"
        path.write_text(
            json.dumps(_payload(expected, predicted, "p01", clip)),
            encoding="utf-8",
        )
        rows.append(load_export(path))

    report = _aggregate(rows)

    assert report["passed"] is False
    assert report["metrics"]["unknown_false_accept_rate"] == 1.0
    assert any("false-accept" in failure for failure in report["failures"])


def test_duplicate_clip_identifiers_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "agent-a-evaluation-one.json"
    path.write_text(
        json.dumps(_payload("squat", "squat", "p01", "clip01")),
        encoding="utf-8",
    )
    row = load_export(path)

    with pytest.raises(ValueError, match="duplicate"):
        _aggregate([row, row])


def test_gate_rejects_mixed_model_versions(tmp_path: Path) -> None:
    rows = []
    for index, (expected, predicted) in enumerate((
        ("squat", "squat"),
        ("unknown", "unknown"),
    )):
        payload = _payload(expected, predicted, "p01", f"clip{index}")
        payload["model"]["client_model_id"] = f"model-v{index + 1}"
        path = tmp_path / f"agent-a-evaluation-{index}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        rows.append(load_export(path))

    report = _aggregate(rows)

    assert report["passed"] is False
    assert any("mixed model ids" in failure for failure in report["failures"])

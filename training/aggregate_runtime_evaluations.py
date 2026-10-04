"""Aggregate versioned Agent A video-call evaluation exports and enforce gates."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "agent-a-runtime-evaluation/v1"
DEFAULT_REQUIRED_LABELS = (
    "squat",
    "pushup",
    "plank",
    "bicep_curl",
    "alternate_bicep_curl",
    "unknown",
)

V9_SEMANTIC_LABELS = (
    "dumbbell_row",
    "jumping_jack",
    "lateral_raise",
    "lunge",
    "shoulder_press",
    "situp",
    "tricep_extension",
    "burpee",
    "jump_rope",
    "pullup",
    "running_in_place",
    "yoga_tree",
    "yoga_triangle",
)

ACCEPTANCE_PROFILES = {
    "core-v1": {
        "required_labels": DEFAULT_REQUIRED_LABELS,
        "expected_model_id": "mmfit-mediapipe-semantic-v1",
    },
    "semantic-v9": {
        "required_labels": (
            *DEFAULT_REQUIRED_LABELS[:-1],
            *V9_SEMANTIC_LABELS,
            "unknown",
        ),
        "expected_model_id": "mmfit-haa500-semantic-pose-families-v9",
    },
}


def discover_exports(inputs: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for path in inputs:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(path.rglob("agent-a-evaluation-*.json"))
        else:
            raise ValueError(f"input does not exist: {path}")
    return sorted(set(files))


def _latest_confirmed_label(payload: dict[str, Any]) -> str:
    trace = payload["telemetry"].get("trace", [])
    event_labels = [
        str(frame.get("recognizedExercise", "unknown"))
        for frame in trace
        if frame.get("recognitionEvent") in {"exercise_confirmed", "exercise_switched"}
    ]
    if event_labels:
        return event_labels[-1]

    history = payload.get("recognition_history", [])
    if history:
        # The browser stores recognition history newest first.
        return str(history[0].get("exercise", "unknown"))

    report = payload.get("latest_action_report") or {}
    if report.get("recognition_status") == "confirmed":
        return str(report.get("recognized_exercise", "unknown"))
    return "unknown"


def load_export(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"{path}: expected schema_version {SCHEMA_VERSION!r}, "
            f"got {payload.get('schema_version')!r}"
        )
    clip = payload.get("clip")
    telemetry = payload.get("telemetry")
    summary = payload.get("summary")
    if not isinstance(clip, dict) or not isinstance(telemetry, dict) or not isinstance(summary, dict):
        raise ValueError(f"{path}: clip, telemetry and summary objects are required")
    for key in (
        "participant_id",
        "clip_id",
        "expected_exercise",
        "source_type",
        "camera_view",
        "lighting",
        "occlusion",
    ):
        if not str(clip.get(key, "")).strip():
            raise ValueError(f"{path}: clip.{key} is required")
    if not isinstance(clip.get("multi_person"), bool):
        raise ValueError(f"{path}: clip.multi_person must be a boolean")

    frames = int(telemetry.get("frames", 0))
    if frames <= 0:
        raise ValueError(f"{path}: telemetry.frames must be positive")
    if not isinstance(telemetry.get("trace"), list) or not telemetry["trace"]:
        raise ValueError(f"{path}: telemetry.trace must be a non-empty list")

    expected = str(clip["expected_exercise"])
    predicted = _latest_confirmed_label(payload)
    return {
        "path": str(path.resolve()),
        "participant_id": str(clip["participant_id"]),
        "clip_id": str(clip["clip_id"]),
        "expected": expected,
        "predicted": predicted,
        "correct": predicted == expected,
        "source_type": str(clip.get("source_type", "unknown")),
        "camera_view": str(clip.get("camera_view", "unknown")),
        "lighting": str(clip.get("lighting", "unknown")),
        "occlusion": str(clip.get("occlusion", "unknown")),
        "multi_person": bool(clip.get("multi_person", False)),
        "frames": frames,
        "unreliable_frames": int(telemetry.get("unreliableFrames", 0)),
        "exercise_switches": int(telemetry.get("exerciseSwitches", 0)),
        "first_confirmed_latency_ms": summary.get("firstConfirmedLatencyMs"),
        "client_model_id": (payload.get("model") or {}).get("client_model_id"),
        "action_report_schema": (payload.get("model") or {}).get("action_report_schema"),
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _scenario_metrics(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row[key])].append(row)
    return {
        name: {
            "clips": len(group),
            "accuracy": sum(item["correct"] for item in group) / len(group),
        }
        for name, group in sorted(groups.items())
    }


def aggregate(
    rows: list[dict[str, Any]],
    *,
    required_labels: Iterable[str],
    min_participants: int,
    min_clips: int,
    min_clips_per_label: int,
    min_accuracy: float,
    min_known_recall: float,
    max_unknown_false_accept: float,
    max_median_latency_ms: float,
    max_p90_latency_ms: float,
    max_switch_clip_rate: float,
    max_unreliable_rate: float,
    expected_model_id: str | None = None,
) -> dict[str, Any]:
    if not rows:
        raise ValueError("no evaluation exports found")

    duplicate_keys = [
        key for key, count in Counter(
            (row["participant_id"], row["clip_id"]) for row in rows
        ).items() if count > 1
    ]
    if duplicate_keys:
        raise ValueError(f"duplicate participant/clip identifiers: {duplicate_keys}")

    required = list(required_labels)
    per_label: dict[str, Any] = {}
    for label in sorted(set(required) | {row["expected"] for row in rows}):
        label_rows = [row for row in rows if row["expected"] == label]
        per_label[label] = {
            "support": len(label_rows),
            "correct": sum(row["correct"] for row in label_rows),
            "recall": (
                sum(row["correct"] for row in label_rows) / len(label_rows)
                if label_rows else None
            ),
        }

    unknown_rows = [row for row in rows if row["expected"] == "unknown"]
    known_rows = [row for row in rows if row["expected"] != "unknown"]
    known_latencies = [
        float(row["first_confirmed_latency_ms"])
        for row in known_rows
        if row["first_confirmed_latency_ms"] is not None
    ]
    total_frames = sum(row["frames"] for row in rows)
    unreliable_rate = sum(row["unreliable_frames"] for row in rows) / total_frames
    unknown_far = (
        sum(row["predicted"] != "unknown" for row in unknown_rows) / len(unknown_rows)
        if unknown_rows else None
    )
    accuracy = sum(row["correct"] for row in rows) / len(rows)
    switch_clip_rate = sum(row["exercise_switches"] > 0 for row in rows) / len(rows)
    median_latency = statistics.median(known_latencies) if known_latencies else None
    p90_latency = _percentile(known_latencies, 0.9)

    failures: list[str] = []
    participant_count = len({row["participant_id"] for row in rows})
    model_ids = {row["client_model_id"] for row in rows if row["client_model_id"]}
    missing_model_ids = sum(not row["client_model_id"] for row in rows)
    if missing_model_ids:
        failures.append(f"model id missing in {missing_model_ids} clip(s)")
    if len(model_ids) > 1:
        failures.append(f"mixed model ids in one report: {sorted(model_ids)}")
    if expected_model_id is not None and model_ids != {expected_model_id}:
        failures.append(
            f"model ids {sorted(model_ids)} do not match required {expected_model_id!r}"
        )
    if participant_count < min_participants:
        failures.append(f"participants {participant_count} < {min_participants}")
    if len(rows) < min_clips:
        failures.append(f"clips {len(rows)} < {min_clips}")
    for label in required:
        support = int(per_label.get(label, {}).get("support", 0))
        recall = per_label.get(label, {}).get("recall")
        if support < min_clips_per_label:
            failures.append(f"{label} support {support} < {min_clips_per_label}")
        if label != "unknown" and recall is not None and recall < min_known_recall:
            failures.append(f"{label} recall {recall:.3f} < {min_known_recall:.3f}")
    if accuracy < min_accuracy:
        failures.append(f"clip accuracy {accuracy:.3f} < {min_accuracy:.3f}")
    if unknown_far is None:
        failures.append("unknown false-accept rate is unavailable")
    elif unknown_far > max_unknown_false_accept:
        failures.append(
            f"unknown false-accept rate {unknown_far:.3f} > {max_unknown_false_accept:.3f}"
        )
    if median_latency is None:
        failures.append("known-action confirmation latency is unavailable")
    elif median_latency > max_median_latency_ms:
        failures.append(
            f"median confirmation latency {median_latency:.0f}ms > {max_median_latency_ms:.0f}ms"
        )
    if p90_latency is None:
        failures.append("known-action p90 confirmation latency is unavailable")
    elif p90_latency > max_p90_latency_ms:
        failures.append(
            f"p90 confirmation latency {p90_latency:.0f}ms > {max_p90_latency_ms:.0f}ms"
        )
    if switch_clip_rate > max_switch_clip_rate:
        failures.append(
            f"switch clip rate {switch_clip_rate:.3f} > {max_switch_clip_rate:.3f}"
        )
    if unreliable_rate > max_unreliable_rate:
        failures.append(
            f"unreliable frame rate {unreliable_rate:.3f} > {max_unreliable_rate:.3f}"
        )

    return {
        "schema_version": "agent-a-runtime-evaluation-summary/v1",
        "passed": not failures,
        "failures": failures,
        "coverage": {
            "participants": participant_count,
            "clips": len(rows),
            "model_ids": sorted(str(model_id) for model_id in model_ids),
            "required_model_id": expected_model_id,
            "required_labels": required,
            "action_report_schemas": sorted({
                str(row["action_report_schema"])
                for row in rows
                if row["action_report_schema"]
            }),
        },
        "metrics": {
            "clip_accuracy": accuracy,
            "unknown_false_accept_rate": unknown_far,
            "median_first_confirmed_latency_ms": median_latency,
            "p90_first_confirmed_latency_ms": p90_latency,
            "switch_clip_rate": switch_clip_rate,
            "unreliable_frame_rate": unreliable_rate,
            "per_label": per_label,
            "by_source_type": _scenario_metrics(rows, "source_type"),
            "by_camera_view": _scenario_metrics(rows, "camera_view"),
            "by_lighting": _scenario_metrics(rows, "lighting"),
            "by_occlusion": _scenario_metrics(rows, "occlusion"),
            "by_multi_person": _scenario_metrics(rows, "multi_person"),
        },
        "clips": rows,
    }


def write_outputs(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "runtime-evaluation-summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (output_dir / "runtime-evaluation-clips.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(report["clips"][0]))
        writer.writeheader()
        writer.writerows(report["clips"])

    metrics = report["metrics"]
    lines = [
        "# Agent A 真实视频验收结果",
        "",
        f"- 结论：{'PASS' if report['passed'] else 'FAIL'}",
        f"- 参与者：{report['coverage']['participants']}",
        f"- 视频片段：{report['coverage']['clips']}",
        f"- 片段准确率：{metrics['clip_accuracy']:.1%}",
        f"- unknown 误接收率：{metrics['unknown_false_accept_rate'] if metrics['unknown_false_accept_rate'] is not None else 'N/A'}",
        f"- 首次确认中位延迟：{metrics['median_first_confirmed_latency_ms'] if metrics['median_first_confirmed_latency_ms'] is not None else 'N/A'} ms",
        f"- 首次确认 P90 延迟：{metrics['p90_first_confirmed_latency_ms'] if metrics['p90_first_confirmed_latency_ms'] is not None else 'N/A'} ms",
        "",
        "## 未通过项",
        "",
    ]
    lines.extend([f"- {failure}" for failure in report["failures"]] or ["- 无"])
    (output_dir / "runtime-evaluation-summary.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--profile",
        choices=sorted(ACCEPTANCE_PROFILES),
        default="core-v1",
        help="Named acceptance matrix; --required-label can override its labels.",
    )
    parser.add_argument("--required-label", action="append", default=[])
    parser.add_argument("--expected-model-id")
    parser.add_argument("--min-participants", type=int, default=5)
    parser.add_argument("--min-clips", type=int)
    parser.add_argument("--min-clips-per-label", type=int, default=5)
    parser.add_argument("--min-accuracy", type=float, default=0.80)
    parser.add_argument("--min-known-recall", type=float, default=0.70)
    parser.add_argument("--max-unknown-false-accept", type=float, default=0.10)
    parser.add_argument("--max-median-latency-ms", type=float, default=4000)
    parser.add_argument("--max-p90-latency-ms", type=float, default=6000)
    parser.add_argument("--max-switch-clip-rate", type=float, default=0.10)
    parser.add_argument("--max-unreliable-rate", type=float, default=0.30)
    parser.add_argument("--no-fail", action="store_true")
    args = parser.parse_args()

    profile = ACCEPTANCE_PROFILES[args.profile]
    required_labels = args.required_label or profile["required_labels"]
    expected_model_id = args.expected_model_id or profile["expected_model_id"]
    min_clips = args.min_clips
    if min_clips is None:
        min_clips = max(30, len(required_labels) * args.min_clips_per_label)

    files = discover_exports(args.input)
    rows = [load_export(path) for path in files]
    report = aggregate(
        rows,
        required_labels=required_labels,
        min_participants=args.min_participants,
        min_clips=min_clips,
        min_clips_per_label=args.min_clips_per_label,
        min_accuracy=args.min_accuracy,
        min_known_recall=args.min_known_recall,
        max_unknown_false_accept=args.max_unknown_false_accept,
        max_median_latency_ms=args.max_median_latency_ms,
        max_p90_latency_ms=args.max_p90_latency_ms,
        max_switch_clip_rate=args.max_switch_clip_rate,
        max_unreliable_rate=args.max_unreliable_rate,
        expected_model_id=expected_model_id,
    )
    write_outputs(report, args.output_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"] and not args.no_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

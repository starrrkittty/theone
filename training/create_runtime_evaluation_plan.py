"""Create an anonymous, deterministic real-video acceptance capture plan."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

try:
    from training.aggregate_runtime_evaluations import ACCEPTANCE_PROFILES
except ModuleNotFoundError:  # Direct execution: python training/script.py
    from aggregate_runtime_evaluations import ACCEPTANCE_PROFILES


PARTICIPANT_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")

PREFERRED_CAMERA = {
    "pushup": "side",
    "plank": "side",
    "situp": "side",
    "lunge": "oblique",
    "dumbbell_row": "oblique",
    "lateral_raise": "front",
    "jumping_jack": "front",
    "burpee": "side",
    "jump_rope": "front",
    "pullup": "front",
    "running_in_place": "side",
    "yoga_tree": "front",
    "yoga_triangle": "front",
}

FIELDNAMES = (
    "participant_id",
    "clip_id",
    "expected_exercise",
    "required_model_id",
    "source_type",
    "camera_view",
    "lighting",
    "occlusion",
    "multi_person",
    "video_path",
    "export_path",
    "status",
)


def build_plan(profile_name: str, participants: list[str]) -> list[dict[str, str]]:
    if profile_name not in ACCEPTANCE_PROFILES:
        raise ValueError(f"unknown profile: {profile_name}")
    if len(participants) < 5:
        raise ValueError("at least 5 anonymous participants are required")
    normalized = [participant.strip().lower() for participant in participants]
    if len(set(normalized)) != len(normalized):
        raise ValueError("participant ids must be unique")
    invalid = [value for value in normalized if not PARTICIPANT_RE.fullmatch(value)]
    if invalid:
        raise ValueError(f"invalid anonymous participant ids: {invalid}")

    profile = ACCEPTANCE_PROFILES[profile_name]
    rows: list[dict[str, str]] = []
    for participant in normalized:
        for label in profile["required_labels"]:
            camera_view = PREFERRED_CAMERA.get(label, "front")
            clip_id = f"{participant}-{label}-{camera_view}-normal-01"
            rows.append({
                "participant_id": participant,
                "clip_id": clip_id,
                "expected_exercise": label,
                "required_model_id": str(profile["expected_model_id"]),
                "source_type": "live_video_call",
                "camera_view": camera_view,
                "lighting": "normal",
                "occlusion": "none",
                "multi_person": "false",
                "video_path": f"raw/{participant}/{clip_id}.mp4",
                "export_path": f"exports/{clip_id}.json",
                "status": "todo",
            })
    return rows


def write_plan(rows: list[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=sorted(ACCEPTANCE_PROFILES), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--participants",
        nargs="+",
        default=["p01", "p02", "p03", "p04", "p05"],
        help="Anonymous ids only; do not use names or contact details.",
    )
    args = parser.parse_args()

    rows = build_plan(args.profile, args.participants)
    write_plan(rows, args.output)
    labels = len(ACCEPTANCE_PROFILES[args.profile]["required_labels"])
    print(
        f"wrote {len(rows)} clips for {len(args.participants)} participants "
        f"and {labels} labels to {args.output.resolve()}"
    )


if __name__ == "__main__":
    main()

"""Build a pose-extraction manifest from official MM-Fit labels and RGB video."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import cv2


LABEL_MAP = {
    "squats": "squat",
    "lunges": "lunge",
    "bicep_curls": "alternate_bicep_curl",
    "situps": "situp",
    "pushups": "pushup",
    "tricep_extensions": "tricep_extension",
    "dumbbell_rows": "dumbbell_row",
    "jumping_jacks": "jumping_jack",
    "dumbbell_shoulder_press": "shoulder_press",
    "lateral_shoulder_raises": "lateral_raise",
}


def video_info(path: Path) -> tuple[float, float]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open RGB video: {path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    frames = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
    cap.release()
    return fps, frames / fps if frames else 0.0


def find_rgb_video(root: Path, workout_id: str) -> Path:
    matches = list(root.rglob(f"{workout_id}_rgb.mp4"))
    if len(matches) != 1:
        raise FileNotFoundError(
            f"Expected one {workout_id}_rgb.mp4 below {root}, found {len(matches)}"
        )
    return matches[0]


def load_segments(path: Path) -> list[tuple[int, int, int, str]]:
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.reader(handle):
            if row and len(row) >= 4:
                rows.append((int(row[0]), int(row[1]), int(row[2]), row[3].strip()))
    return rows


def path_for_manifest(path: Path, manifest_parent: Path) -> str:
    try:
        return path.resolve().relative_to(manifest_parent.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--unknown-min-seconds", type=float, default=2.0)
    parser.add_argument("--unknown-max-seconds", type=float, default=8.0)
    args = parser.parse_args()

    root = args.dataset_root.resolve()
    label_files = sorted(root.rglob("w*_labels.csv"))
    if not label_files:
        raise FileNotFoundError(f"No w*_labels.csv files found below {root}")
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []

    for label_path in label_files:
        workout_id = label_path.stem.removesuffix("_labels")
        video_path = find_rgb_video(root, workout_id)
        fps, duration = video_info(video_path)
        path_value = path_for_manifest(video_path, output.parent)
        segments = sorted(load_segments(label_path), key=lambda row: row[0])
        previous_end = 0.0
        for start_frame, end_frame, reps, raw_label in segments:
            start_sec = start_frame / fps
            end_sec = end_frame / fps
            if start_sec - previous_end >= args.unknown_min_seconds:
                entries.append({
                    "path": path_value,
                    "label": "unknown",
                    "subject": workout_id,
                    "start_sec": round(max(previous_end, start_sec - args.unknown_max_seconds), 3),
                    "end_sec": round(start_sec, 3),
                    "source_label": "non_activity",
                })
            mapped = LABEL_MAP.get(raw_label)
            if mapped:
                entries.append({
                    "path": path_value,
                    "label": mapped,
                    "subject": workout_id,
                    "start_sec": round(start_sec, 3),
                    "end_sec": round(end_sec, 3),
                    "repetitions": reps,
                    "source_label": raw_label,
                })
            previous_end = max(previous_end, end_sec)
        if duration - previous_end >= args.unknown_min_seconds:
            entries.append({
                "path": path_value,
                "label": "unknown",
                "subject": workout_id,
                "start_sec": round(previous_end, 3),
                "end_sec": round(min(duration, previous_end + args.unknown_max_seconds), 3),
                "source_label": "non_activity",
            })

    output.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["label"]] = counts.get(entry["label"], 0) + 1
    print(f"saved {len(entries)} segments from {len(label_files)} workouts to {output}")
    print(f"segment counts: {counts}")


if __name__ == "__main__":
    main()


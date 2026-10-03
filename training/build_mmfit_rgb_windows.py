"""Extract product-domain MediaPipe windows from selected MM-Fit RGB videos.

The official MM-Fit pose files use a different pose estimator.  This script
reruns the same MediaPipe Pose Landmarker model used by the browser so public
RGB data can be used for domain adaptation and held-out evaluation.

Processing is deliberately sequential and shard based.  A single decoded
segment is held in memory at a time and the final dataset is memory mapped.
"""

from __future__ import annotations

import argparse
import csv
import json
import tempfile
from collections import Counter
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from build_mmfit_pose_windows import PARTICIPANT_BY_WORKOUT, starts_for
from dataset_io import create_dataset
from prepare_mmfit_manifest import LABEL_MAP


KEY_JOINT_INDICES = [11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28, 0, 7, 8, 9, 10]


def load_labels(path: Path) -> list[tuple[int, int, int, str]]:
    rows: list[tuple[int, int, int, str]] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.reader(handle):
            if row and len(row) >= 4:
                rows.append((int(row[0]), int(row[1]), int(row[2]), row[3].strip()))
    return sorted(rows, key=lambda item: item[0])


def labelled_and_unknown_segments(
    rows: list[tuple[int, int, int, str]],
    frame_count: int,
) -> list[tuple[int, int, str]]:
    """Return source-frame intervals, retaining gaps as explicit unknown."""
    segments: list[tuple[int, int, str]] = []
    cursor = 0
    for start, end, _, source_label in rows:
        start = max(0, start)
        end = min(frame_count - 1, end)
        if start > cursor:
            segments.append((cursor, start - 1, "unknown"))
        mapped = LABEL_MAP.get(source_label)
        if mapped and end >= start:
            segments.append((start, end, mapped))
        cursor = max(cursor, end + 1)
    if cursor < frame_count:
        segments.append((cursor, frame_count - 1, "unknown"))
    return segments


def normalise_landmarks(
    result,
    min_visibility: float,
    coordinate_mode: str,
) -> np.ndarray | None:
    if not result.pose_landmarks:
        return None
    landmarks = result.pose_landmarks[0]
    core = [landmarks[index] for index in (11, 12, 23, 24)]
    if min(point.visibility for point in core) < min_visibility:
        return None

    left_hip, right_hip = landmarks[23], landmarks[24]
    left_shoulder, right_shoulder = landmarks[11], landmarks[12]
    hip = np.array(
        [
            (left_hip.x + right_hip.x) / 2.0,
            (left_hip.y + right_hip.y) / 2.0,
            (left_hip.z + right_hip.z) / 2.0,
        ],
        dtype=np.float32,
    )
    shoulder = np.array(
        [
            (left_shoulder.x + right_shoulder.x) / 2.0,
            (left_shoulder.y + right_shoulder.y) / 2.0,
            (left_shoulder.z + right_shoulder.z) / 2.0,
        ],
        dtype=np.float32,
    )
    torso_delta = shoulder - hip
    if coordinate_mode == "xy":
        torso_delta[2] = 0.0
    torso = float(np.linalg.norm(torso_delta))
    if not np.isfinite(torso) or torso <= 1e-6:
        return None

    frame = np.empty((len(KEY_JOINT_INDICES), 3), dtype=np.float32)
    for output_index, landmark_index in enumerate(KEY_JOINT_INDICES):
        point = landmarks[landmark_index]
        frame[output_index] = (
            np.array([point.x, point.y, point.z], dtype=np.float32) - hip
        ) / torso
    return frame


def extract_runs(
    capture: cv2.VideoCapture,
    landmarker: vision.PoseLandmarker,
    start_frame: int,
    end_frame: int,
    frame_step: int,
    min_visibility: float,
    coordinate_mode: str,
    fps: float,
    timestamp_offset_ms: int,
    max_image_size: int,
) -> list[np.ndarray]:
    """Extract contiguous valid sampled runs without bridging pose dropouts."""
    capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    frame_number = start_frame
    current: list[np.ndarray] = []
    runs: list[np.ndarray] = []
    while frame_number <= end_frame:
        ok, bgr = capture.read()
        if not ok:
            break
        if (frame_number - start_frame) % frame_step == 0:
            longest = max(bgr.shape[:2])
            if max_image_size > 0 and longest > max_image_size:
                scale = max_image_size / longest
                bgr = cv2.resize(
                    bgr,
                    (max(1, round(bgr.shape[1] * scale)), max(1, round(bgr.shape[0] * scale))),
                    interpolation=cv2.INTER_AREA,
                )
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            timestamp_ms = timestamp_offset_ms + int(round(frame_number * 1000.0 / fps))
            frame = normalise_landmarks(
                landmarker.detect_for_video(image, timestamp_ms),
                min_visibility,
                coordinate_mode,
            )
            if frame is None:
                if current:
                    runs.append(np.stack(current))
                    current = []
            else:
                current.append(frame)
        frame_number += 1
    if current:
        runs.append(np.stack(current))
    return runs


def windows_from_runs(
    runs: list[np.ndarray],
    window: int,
    stride: int,
    maximum: int,
) -> np.ndarray:
    candidates: list[np.ndarray] = []
    for run in runs:
        for start in range(0, len(run) - window + 1, stride):
            candidates.append(run[start : start + window])
    if maximum > 0 and len(candidates) > maximum:
        selected = np.linspace(0, len(candidates) - 1, maximum, dtype=int)
        candidates = [candidates[index] for index in selected]
    if not candidates:
        return np.empty((0, window, len(KEY_JOINT_INDICES), 3), dtype=np.float32)
    return np.stack(candidates).astype(np.float32)


def save_shard(
    path: Path,
    windows: np.ndarray,
    label_id: int,
    participant: str,
    workout: str,
) -> None:
    count = len(windows)
    np.savez_compressed(
        path,
        x=windows,
        y=np.full(count, label_id, dtype=np.int64),
        subjects=np.full(count, participant),
        clips=np.full(count, workout),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--rgb-root", type=Path, required=True)
    parser.add_argument("--pose-model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workouts", nargs="*", default=[])
    parser.add_argument("--target-fps", type=float, default=15.0)
    parser.add_argument("--window", type=int, default=30)
    parser.add_argument("--stride", type=int, default=8)
    parser.add_argument("--max-windows-per-segment", type=int, default=120)
    parser.add_argument("--max-unknown-windows-per-gap", type=int, default=24)
    parser.add_argument("--min-visibility", type=float, default=0.45)
    parser.add_argument("--coordinate-mode", choices=["xy", "xyz"], default="xy")
    parser.add_argument("--max-image-size", type=int, default=640)
    args = parser.parse_args()

    labels = sorted(set(LABEL_MAP.values()) | {"unknown"})
    label_to_id = {label: index for index, label in enumerate(labels)}
    selected = set(args.workouts)
    videos = sorted(args.rgb_root.glob("w*_rgb.mp4"))
    if selected:
        videos = [path for path in videos if path.stem.removesuffix("_rgb") in selected]
    if not videos:
        raise FileNotFoundError(f"No selected MM-Fit RGB videos below {args.rgb_root}")

    args.output.mkdir(parents=True, exist_ok=True)
    counts = Counter()
    processed: list[dict[str, object]] = []
    base_options = python.BaseOptions(model_asset_path=str(args.pose_model.resolve()))
    options = vision.PoseLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    with tempfile.TemporaryDirectory(prefix="mmfit-rgb-shards-", dir=args.output.parent) as temp:
        shard_paths: list[Path] = []
        shard_index = 0
        timestamp_offset_ms = 0
        with vision.PoseLandmarker.create_from_options(options) as landmarker:
            for video_path in videos:
                workout = video_path.stem.removesuffix("_rgb")
                participant = PARTICIPANT_BY_WORKOUT.get(workout)
                label_path = next(args.dataset_root.rglob(f"{workout}_labels.csv"), None)
                if participant is None or label_path is None:
                    print(f"skip {workout}: participant or labels missing")
                    continue

                capture = cv2.VideoCapture(str(video_path))
                if not capture.isOpened():
                    print(f"skip {workout}: video cannot be opened")
                    continue
                fps = float(capture.get(cv2.CAP_PROP_FPS))
                frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
                if fps <= 0 or frame_count <= 0:
                    capture.release()
                    print(f"skip {workout}: invalid video metadata")
                    continue
                frame_step = max(1, int(round(fps / args.target_fps)))
                workout_counts = Counter()
                segments = labelled_and_unknown_segments(load_labels(label_path), frame_count)
                for segment_index, (start, end, label) in enumerate(segments, start=1):
                    runs = extract_runs(
                        capture,
                        landmarker,
                        start,
                        end,
                        frame_step,
                        args.min_visibility,
                        args.coordinate_mode,
                        fps,
                        timestamp_offset_ms,
                        args.max_image_size,
                    )
                    maximum = (
                        args.max_unknown_windows_per_gap
                        if label == "unknown"
                        else args.max_windows_per_segment
                    )
                    windows = windows_from_runs(runs, args.window, args.stride, maximum)
                    if len(windows) == 0:
                        continue
                    shard = Path(temp) / f"{shard_index:06d}.npz"
                    save_shard(shard, windows, label_to_id[label], participant, workout)
                    shard_paths.append(shard)
                    counts[label] += len(windows)
                    workout_counts[label] += len(windows)
                    shard_index += 1
                    if segment_index % 5 == 0 or segment_index == len(segments):
                        print(
                            f"{workout}: segment {segment_index}/{len(segments)} "
                            f"windows={sum(workout_counts.values())}",
                            flush=True,
                        )
                capture.release()
                timestamp_offset_ms += int(round(frame_count * 1000.0 / fps)) + 1000
                processed.append(
                    {
                        "workout": workout,
                        "participant": participant,
                        "fps": fps,
                        "frame_count": frame_count,
                        "frame_step": frame_step,
                        "windows": dict(workout_counts),
                    }
                )
                print(
                    f"processed {workout} participant={participant} "
                    f"windows={sum(workout_counts.values())}",
                    flush=True,
                )

        if not shard_paths:
            raise RuntimeError("No valid RGB pose windows were extracted")
        metadata = create_dataset(args.output, shard_paths, labels)

    provenance = {
        "source": "MM-Fit RGB videos processed with product MediaPipe Pose Landmarker Lite",
        "domain": "product_pose_domain_adaptation",
        "deployable_without_held_out_evaluation": False,
        "pose_model": str(args.pose_model.resolve()),
        "joint_indices": KEY_JOINT_INDICES,
        "target_fps": args.target_fps,
        "coordinate_mode": args.coordinate_mode,
        "normalization_mode": f"torso_{args.coordinate_mode}",
        "workouts": processed,
        "windows_per_label": dict(counts),
    }
    (args.output / "provenance.json").write_text(
        json.dumps(provenance, indent=2), encoding="utf-8"
    )
    print(f"saved {metadata['samples']} windows to {args.output}")
    print(f"windows per label: {dict(counts)}")


if __name__ == "__main__":
    main()

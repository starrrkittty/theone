"""Convert labelled RGB video intervals into MediaPipe skeleton windows.

The output NPZ deliberately contains subject IDs so train/validation/test
splits can be made by person/session instead of leaking adjacent frames across
splits.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np


WINDOW = 30
STRIDE = 10
KEY_JOINT_INDICES = [11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28, 0, 7, 8, 9, 10]
SUPPORTED_LABELS = {
    "squat",
    "pushup",
    "plank",
    "bicep_curl",
    "alternate_bicep_curl",
    "unknown",
}


def validate_manifest(entries: list[dict], root: Path) -> None:
    if not entries:
        raise ValueError("Manifest is empty")
    required = {"path", "label", "subject"}
    label_subjects: dict[str, set[str]] = defaultdict(set)
    missing_files = []
    for index, entry in enumerate(entries):
        missing = required - entry.keys()
        if missing:
            raise ValueError(f"Manifest entry {index} is missing fields: {sorted(missing)}")
        label = str(entry["label"])
        if label not in SUPPORTED_LABELS:
            raise ValueError(f"Unsupported label in entry {index}: {label}")
        label_subjects[label].add(str(entry["subject"]))
        path = (root / entry["path"]).resolve()
        if not path.is_file():
            missing_files.append(str(path))
    if missing_files:
        preview = "\n".join(missing_files[:5])
        raise FileNotFoundError(f"Manifest references missing videos:\n{preview}")
    if len({str(entry["subject"]) for entry in entries}) < 3:
        raise ValueError("Need at least three subjects/sessions for train/validation/test")
    sparse = {label: len(subjects) for label, subjects in label_subjects.items() if len(subjects) < 3}
    if sparse:
        print(f"warning: labels present in fewer than three subjects/sessions: {sparse}")


def normalized_frame(landmarks) -> np.ndarray | None:
    if len(landmarks) != 33:
        return None
    xyz = np.asarray([[lm.x, lm.y, lm.z] for lm in landmarks], dtype=np.float32)
    visibility = np.asarray([getattr(lm, "visibility", 0.0) for lm in landmarks])
    if np.mean(visibility[[11, 12, 23, 24]] >= 0.3) < 0.75:
        return None
    hip = (xyz[23] + xyz[24]) / 2.0
    shoulder = (xyz[11] + xyz[12]) / 2.0
    torso = float(np.linalg.norm(shoulder - hip))
    if torso < 1e-6:
        return None
    return ((xyz[KEY_JOINT_INDICES] - hip) / torso).astype(np.float32)


def process_segment(detector, entry: dict, model_root: Path) -> list[np.ndarray]:
    video_path = (model_root / entry["path"]).resolve()
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    start_sec = float(entry.get("start_sec", 0.0))
    end_sec = float(entry.get("end_sec", float("inf")))
    cap.set(cv2.CAP_PROP_POS_MSEC, start_sec * 1000.0)
    frames: list[np.ndarray] = []
    frame_index = int(round(start_sec * fps))
    while cap.isOpened():
        ok, bgr = cap.read()
        if not ok:
            break
        time_sec = frame_index / fps
        if time_sec > end_sec:
            break
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = detector.detect_for_video(image, int(round(time_sec * 1000.0)))
        if result.pose_landmarks:
            frame = normalized_frame(result.pose_landmarks[0])
            if frame is not None:
                frames.append(frame)
        frame_index += 1
    cap.release()
    return frames


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--window", type=int, default=WINDOW)
    parser.add_argument("--stride", type=int, default=STRIDE)
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    entries = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError("Manifest root must be a JSON list")
    validate_manifest(entries, manifest_path.parent)
    labels = sorted({str(entry["label"]) for entry in entries})
    label_to_id = {label: index for index, label in enumerate(labels)}

    options = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(args.model.resolve())),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    windows: list[np.ndarray] = []
    targets: list[int] = []
    subjects: list[str] = []
    clips: list[str] = []
    with mp.tasks.vision.PoseLandmarker.create_from_options(options) as detector:
        for entry in entries:
            frames = process_segment(detector, entry, manifest_path.parent)
            for start in range(0, len(frames) - args.window + 1, args.stride):
                windows.append(np.stack(frames[start:start + args.window]))
                targets.append(label_to_id[str(entry["label"])])
                subjects.append(str(entry["subject"]))
                clips.append(str(entry["path"]))

    if not windows:
        raise RuntimeError("No valid pose windows were produced")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output,
        x=np.stack(windows).astype(np.float32),
        y=np.asarray(targets, dtype=np.int64),
        subjects=np.asarray(subjects),
        clips=np.asarray(clips),
        labels=np.asarray(labels),
    )
    print(f"saved {len(windows)} windows to {args.output}")
    print(f"labels: {labels}")
    print(f"windows per label: {dict(Counter(labels[target] for target in targets))}")
    print(f"subjects/sessions: {len(set(subjects))}")


if __name__ == "__main__":
    main()

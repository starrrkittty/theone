"""Convert labelled RGB intervals into memory-mapped MediaPipe windows."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

from dataset_io import create_dataset


WINDOW = 30
STRIDE = 10
KEY_JOINT_INDICES = [11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28, 0, 7, 8, 9, 10]
SUPPORTED_LABELS = {
    "squat", "pushup", "plank", "bicep_curl", "alternate_bicep_curl",
    "lunge", "situp", "tricep_extension", "dumbbell_row",
    "jumping_jack", "shoulder_press", "lateral_raise", "unknown",
}


def resolve_video_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


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
        path = resolve_video_path(root, str(entry["path"]))
        if not path.is_file():
            missing_files.append(str(path))
    if missing_files:
        preview = "\n".join(missing_files[:5])
        raise FileNotFoundError(f"Manifest references missing videos:\n{preview}")
    if len({str(entry["subject"]) for entry in entries}) < 3:
        raise ValueError("Need at least three subjects/sessions for train/validation/test")
    sparse = {
        label: len(subjects) for label, subjects in label_subjects.items()
        if len(subjects) < 3
    }
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


def process_segment(detector, entry: dict, root: Path) -> list[np.ndarray]:
    video_path = resolve_video_path(root, str(entry["path"]))
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


def available_memory_gb() -> float | None:
    if os.name != "nt":
        return None
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong),
            ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
            ("total_page_file", ctypes.c_ulonglong), ("avail_page_file", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
            ("avail_extended_virtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return status.avail_phys / (1024 ** 3)
    return None


def choose_workers(requested: int, reserve_gb: float, worker_gb: float) -> int:
    upper = requested if requested > 0 else min(4, max(1, (os.cpu_count() or 2) // 2))
    available = available_memory_gb()
    if available is None:
        return min(2, upper)
    safe_by_memory = max(1, int(max(0.0, available - reserve_gb) // worker_gb))
    return max(1, min(upper, safe_by_memory))


def window_starts(frame_count: int, window: int, stride: int, maximum: int) -> list[int]:
    starts = list(range(0, frame_count - window + 1, stride))
    if maximum > 0 and len(starts) > maximum:
        positions = np.linspace(0, len(starts) - 1, maximum, dtype=int)
        return [starts[index] for index in positions]
    return starts


def process_entry_to_shard(
    index: int, entry: dict, manifest_root: str, model_path: str,
    shard_dir: str, label_to_id: dict[str, int], window: int,
    stride: int, max_windows: int,
) -> tuple[str, int, str]:
    options = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    with mp.tasks.vision.PoseLandmarker.create_from_options(options) as detector:
        frames = process_segment(detector, entry, Path(manifest_root))
    starts = window_starts(len(frames), window, stride, max_windows)
    if starts:
        x = np.stack([
            np.stack(frames[start:start + window]) for start in starts
        ]).astype(np.float32)
    else:
        x = np.empty((0, window, len(KEY_JOINT_INDICES), 3), dtype=np.float32)
    count = len(x)
    shard_path = Path(shard_dir) / f"{index:05d}.npz"
    np.savez_compressed(
        shard_path, x=x,
        y=np.full(count, label_to_id[str(entry["label"])], dtype=np.int64),
        subjects=np.full(count, str(entry["subject"])),
        clips=np.full(count, str(entry["path"])),
    )
    return str(shard_path), count, str(entry["label"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Output dataset directory")
    parser.add_argument("--window", type=int, default=WINDOW)
    parser.add_argument("--stride", type=int, default=STRIDE)
    parser.add_argument("--workers", type=int, default=0, help="0 selects a RAM-aware value")
    parser.add_argument("--memory-reserve-gb", type=float, default=4.0)
    parser.add_argument("--estimated-worker-gb", type=float, default=1.5)
    parser.add_argument("--max-windows-per-segment", type=int, default=160)
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    entries = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError("Manifest root must be a JSON list")
    validate_manifest(entries, manifest_path.parent)
    labels = sorted({str(entry["label"]) for entry in entries})
    label_to_id = {label: index for index, label in enumerate(labels)}

    workers = choose_workers(args.workers, args.memory_reserve_gb, args.estimated_worker_gb)
    available = available_memory_gb()
    available_text = f"{available:.1f}" if available is not None else "unknown"
    print(f"using {workers} extraction worker(s); available_ram_gb={available_text}")
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pose-shards-", dir=args.output.parent) as shard_dir:
        shard_paths: list[Path] = []
        counts = Counter()
        with ProcessPoolExecutor(max_workers=workers) as pool:
            pending = {}
            next_index = 0
            while next_index < len(entries) or pending:
                while next_index < len(entries) and len(pending) < workers * 2:
                    future = pool.submit(
                        process_entry_to_shard, next_index, entries[next_index],
                        str(manifest_path.parent), str(args.model.resolve()), shard_dir,
                        label_to_id, args.window, args.stride,
                        args.max_windows_per_segment,
                    )
                    pending[future] = next_index
                    next_index += 1
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    index = pending.pop(future)
                    shard_path, count, label = future.result()
                    shard_paths.append(Path(shard_path))
                    counts[label] += count
                    print(f"segment={index + 1}/{len(entries)} label={label} windows={count}")
        metadata = create_dataset(args.output, sorted(shard_paths), labels)
    print(f"saved {metadata['samples']} windows to {args.output}")
    print(f"labels: {labels}")
    print(f"windows per label: {dict(counts)}")
    print(f"subjects/sessions: {len({str(entry['subject']) for entry in entries})}")


if __name__ == "__main__":
    main()

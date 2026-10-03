"""Build a public-data pretraining set from MM-Fit COCO 2D poses.

This is deliberately marked as a source-domain pretraining dataset.  Product
deployment still requires MediaPipe-extracted RGB fine-tuning/evaluation.
"""

from __future__ import annotations

import argparse
import csv
import json
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np

from dataset_io import create_dataset
from prepare_mmfit_manifest import LABEL_MAP


PARTICIPANT_BY_WORKOUT = {
    "w00": "p02", "w01": "p00", "w02": "p01", "w03": "p00",
    "w04": "p01", "w05": "p02", "w06": "p00", "w07": "p01",
    "w08": "p00", "w09": "p01", "w10": "p00", "w11": "p01",
    "w12": "p03", "w13": "p04", "w14": "p00", "w15": "p01",
    "w16": "p05", "w17": "p06", "w18": "p07", "w19": "p08",
    "w20": "p09",
}

# Product order:
# L/R shoulder, elbow, wrist, hip, knee, ankle, nose, L/R ear, L/R eye.
# Eyes occupy the two facial slots that are mouth corners in MediaPipe.  They
# carry little exercise signal but preserve the expected 17-joint tensor.
COCO_TO_PRODUCT = [5, 2, 6, 3, 7, 4, 11, 8, 12, 9, 13, 10, 0, 17, 16, 15, 14]


def load_labels(path: Path) -> list[tuple[int, int, int, str]]:
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.reader(handle):
            if row and len(row) >= 4:
                rows.append((int(row[0]), int(row[1]), int(row[2]), row[3].strip()))
    return sorted(rows, key=lambda item: item[0])


def normalize_pose(raw: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Convert [2,T,18] COCO pixels to [T,17,3] torso-normalized coordinates."""
    coords = raw.transpose(1, 2, 0).astype(np.float32)
    left_hip, right_hip = coords[:, 11], coords[:, 8]
    left_shoulder, right_shoulder = coords[:, 5], coords[:, 2]
    hip = (left_hip + right_hip) / 2.0
    shoulder = (left_shoulder + right_shoulder) / 2.0
    torso = np.linalg.norm(shoulder - hip, axis=1)
    core_nonzero = np.all(
        np.linalg.norm(coords[:, [2, 5, 8, 11]], axis=2) > 0.0,
        axis=1,
    )
    valid = np.isfinite(torso) & (torso > 1e-6) & core_nonzero
    selected = coords[:, COCO_TO_PRODUCT]
    out = np.zeros((len(coords), len(COCO_TO_PRODUCT), 3), dtype=np.float32)
    out[valid, :, :2] = (
        selected[valid] - hip[valid, None, :]
    ) / torso[valid, None, None]
    return out, valid


def starts_for(frame_count: int, window: int, stride: int, maximum: int) -> list[int]:
    starts = list(range(0, frame_count - window + 1, stride))
    if maximum > 0 and len(starts) > maximum:
        selected = np.linspace(0, len(starts) - 1, maximum, dtype=int)
        return [starts[index] for index in selected]
    return starts


def segment_windows(
    pose: np.ndarray,
    frame_numbers: np.ndarray,
    start_frame: int,
    end_frame: int,
    *,
    window: int,
    stride: int,
    maximum: int,
    min_valid_ratio: float,
    frame_step: int,
) -> np.ndarray:
    left = int(np.searchsorted(frame_numbers, start_frame, side="left"))
    right = int(np.searchsorted(frame_numbers, end_frame, side="right"))
    normalized, valid = normalize_pose(pose[:, left:right, 1:])
    normalized = normalized[::frame_step]
    valid = valid[::frame_step]
    windows = []
    for start in starts_for(len(normalized), window, stride, maximum):
        stop = start + window
        if float(valid[start:stop].mean()) >= min_valid_ratio:
            windows.append(normalized[start:stop])
    if not windows:
        return np.empty((0, window, len(COCO_TO_PRODUCT), 3), dtype=np.float32)
    return np.stack(windows).astype(np.float32)


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
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--window", type=int, default=30)
    parser.add_argument("--stride", type=int, default=10)
    parser.add_argument("--max-windows-per-segment", type=int, default=160)
    parser.add_argument("--max-unknown-windows-per-gap", type=int, default=40)
    parser.add_argument("--min-valid-ratio", type=float, default=0.9)
    parser.add_argument("--source-fps", type=float, default=30.0)
    parser.add_argument("--target-fps", type=float, default=15.0)
    args = parser.parse_args()

    frame_step = max(1, int(round(args.source_fps / args.target_fps)))

    root = args.dataset_root.resolve()
    workout_dirs = sorted(path.parent for path in root.rglob("w*_labels.csv"))
    if not workout_dirs:
        raise FileNotFoundError(f"No MM-Fit workout labels below {root}")
    labels = sorted(set(LABEL_MAP.values()) | {"unknown"})
    label_to_id = {label: index for index, label in enumerate(labels)}
    args.output.mkdir(parents=True, exist_ok=True)

    counts = Counter()
    provenance = {
        "source": "MM-Fit pose_2d COCO-18",
        "domain": "public_pose_pretraining",
        "deployable_without_rgb_finetune": False,
        "participant_split_key": "official MM-Fit participant id",
        "coco_to_product_joint_indices": COCO_TO_PRODUCT,
        "source_fps": args.source_fps,
        "target_fps": args.target_fps,
        "frame_step": frame_step,
    }
    with tempfile.TemporaryDirectory(prefix="mmfit-pose-shards-", dir=args.output.parent) as temp:
        shard_paths: list[Path] = []
        shard_index = 0
        for workout_dir in workout_dirs:
            workout = workout_dir.name
            pose_path = workout_dir / f"{workout}_pose_2d.npy"
            label_path = workout_dir / f"{workout}_labels.csv"
            if not pose_path.is_file() or workout not in PARTICIPANT_BY_WORKOUT:
                continue
            pose = np.load(pose_path, mmap_mode="r", allow_pickle=False)
            frame_numbers = np.asarray(pose[0, :, 0])
            source_segments = load_labels(label_path)
            participant = PARTICIPANT_BY_WORKOUT[workout]

            previous_end = int(frame_numbers[0])
            for start_frame, end_frame, _, source_label in source_segments:
                if start_frame - previous_end >= args.window:
                    windows = segment_windows(
                        pose, frame_numbers, previous_end, start_frame - 1,
                        window=args.window, stride=args.stride,
                        maximum=args.max_unknown_windows_per_gap,
                        min_valid_ratio=args.min_valid_ratio,
                        frame_step=frame_step,
                    )
                    shard = Path(temp) / f"{shard_index:05d}.npz"
                    save_shard(shard, windows, label_to_id["unknown"], participant, workout)
                    shard_paths.append(shard)
                    counts["unknown"] += len(windows)
                    shard_index += 1

                label = LABEL_MAP.get(source_label)
                if label:
                    windows = segment_windows(
                        pose, frame_numbers, start_frame, end_frame,
                        window=args.window, stride=args.stride,
                        maximum=args.max_windows_per_segment,
                        min_valid_ratio=args.min_valid_ratio,
                        frame_step=frame_step,
                    )
                    shard = Path(temp) / f"{shard_index:05d}.npz"
                    save_shard(shard, windows, label_to_id[label], participant, workout)
                    shard_paths.append(shard)
                    counts[label] += len(windows)
                    shard_index += 1
                previous_end = max(previous_end, end_frame + 1)

            final_frame = int(frame_numbers[-1])
            if final_frame - previous_end >= args.window:
                windows = segment_windows(
                    pose, frame_numbers, previous_end, final_frame,
                    window=args.window, stride=args.stride,
                    maximum=args.max_unknown_windows_per_gap,
                    min_valid_ratio=args.min_valid_ratio,
                    frame_step=frame_step,
                )
                shard = Path(temp) / f"{shard_index:05d}.npz"
                save_shard(shard, windows, label_to_id["unknown"], participant, workout)
                shard_paths.append(shard)
                counts["unknown"] += len(windows)
                shard_index += 1
            print(f"processed {workout} participant={participant}")

        metadata = create_dataset(args.output, shard_paths, labels)

    (args.output / "provenance.json").write_text(
        json.dumps(provenance, indent=2), encoding="utf-8"
    )
    print(f"saved {metadata['samples']} windows to {args.output}")
    print(f"labels: {labels}")
    print(f"windows per label: {dict(counts)}")


if __name__ == "__main__":
    main()


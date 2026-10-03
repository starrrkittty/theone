"""Memory-mapped dataset helpers for large pose-window corpora."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def create_dataset(output_dir: Path, shard_paths: list[Path], labels: list[str]) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    shard_meta: list[tuple[Path, int]] = []
    total = 0
    max_subject = 1
    max_clip = 1
    for shard_path in shard_paths:
        with np.load(shard_path, allow_pickle=False) as shard:
            count = int(len(shard["y"]))
            if count == 0:
                continue
            shard_meta.append((shard_path, count))
            total += count
            max_subject = max(max_subject, max(map(len, shard["subjects"].astype(str))))
            max_clip = max(max_clip, max(map(len, shard["clips"].astype(str))))
    if total == 0:
        raise RuntimeError("No valid pose windows were produced")

    with np.load(shard_meta[0][0], allow_pickle=False) as first:
        sample_shape = tuple(first["x"].shape[1:])
    x = np.lib.format.open_memmap(
        output_dir / "x.npy", mode="w+", dtype=np.float32,
        shape=(total, *sample_shape),
    )
    y = np.lib.format.open_memmap(
        output_dir / "y.npy", mode="w+", dtype=np.int64, shape=(total,)
    )
    subjects = np.lib.format.open_memmap(
        output_dir / "subjects.npy", mode="w+", dtype=f"<U{max_subject}",
        shape=(total,),
    )
    clips = np.lib.format.open_memmap(
        output_dir / "clips.npy", mode="w+", dtype=f"<U{max_clip}",
        shape=(total,),
    )
    cursor = 0
    for shard_path, count in shard_meta:
        with np.load(shard_path, allow_pickle=False) as shard:
            end = cursor + count
            x[cursor:end] = shard["x"]
            y[cursor:end] = shard["y"]
            subjects[cursor:end] = shard["subjects"].astype(str)
            clips[cursor:end] = shard["clips"].astype(str)
            cursor = end
    for array in (x, y, subjects, clips):
        array.flush()

    metadata = {
        "format": "pose-windows-v1",
        "samples": total,
        "sample_shape": list(sample_shape),
        "labels": labels,
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    return metadata


def load_dataset(path: Path, mmap_mode: str = "r") -> dict[str, np.ndarray]:
    if path.is_dir():
        metadata = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
        return {
            "x": np.load(path / "x.npy", mmap_mode=mmap_mode, allow_pickle=False),
            "y": np.load(path / "y.npy", mmap_mode=mmap_mode, allow_pickle=False),
            "subjects": np.load(path / "subjects.npy", mmap_mode=mmap_mode, allow_pickle=False),
            "clips": np.load(path / "clips.npy", mmap_mode=mmap_mode, allow_pickle=False),
            "labels": np.asarray(metadata["labels"]),
        }
    data = np.load(path, mmap_mode=mmap_mode, allow_pickle=False)
    return {key: data[key] for key in ("x", "y", "subjects", "clips", "labels")}


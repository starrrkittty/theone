"""Merge compatible memory-mapped pose-window datasets without loading them into RAM."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

try:
    from .dataset_io import load_dataset
except ImportError:  # Direct script execution: python training/merge_datasets.py
    from dataset_io import load_dataset


def merged_label_order(datasets) -> list[str]:
    """Preserve the first dataset order and append genuinely new labels."""
    labels: list[str] = []
    seen: set[str] = set()
    for data in datasets:
        for label in data["labels"].astype(str).tolist():
            if label not in seen:
                labels.append(label)
                seen.add(label)
    return labels


def remap_targets(targets, source_labels: list[str], merged_labels: list[str]):
    mapping = np.asarray(
        [merged_labels.index(label) for label in source_labels], dtype=np.int64
    )
    values = np.asarray(targets, dtype=np.int64)
    if values.size and (values.min() < 0 or values.max() >= len(source_labels)):
        raise ValueError("Dataset contains a target id outside its label table")
    return mapping[values]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chunk-size", type=int, default=1024)
    args = parser.parse_args()

    datasets = [load_dataset(path, mmap_mode="r") for path in args.inputs]
    labels = merged_label_order(datasets)
    sample_shape = tuple(datasets[0]["x"].shape[1:])
    for path, data in zip(args.inputs, datasets):
        if tuple(data["x"].shape[1:]) != sample_shape:
            raise ValueError(f"Sample shape differs in {path}: {data['x'].shape[1:]}")

    total = sum(len(data["y"]) for data in datasets)
    max_subject = max(max(map(len, data["subjects"].astype(str))) for data in datasets)
    max_clip = max(max(map(len, data["clips"].astype(str))) for data in datasets)
    args.output.mkdir(parents=True, exist_ok=True)
    outputs = {
        "x": np.lib.format.open_memmap(
            args.output / "x.npy", mode="w+", dtype=np.float32, shape=(total, *sample_shape)
        ),
        "y": np.lib.format.open_memmap(
            args.output / "y.npy", mode="w+", dtype=np.int64, shape=(total,)
        ),
        "subjects": np.lib.format.open_memmap(
            args.output / "subjects.npy", mode="w+", dtype=f"<U{max_subject}", shape=(total,)
        ),
        "clips": np.lib.format.open_memmap(
            args.output / "clips.npy", mode="w+", dtype=f"<U{max_clip}", shape=(total,)
        ),
    }
    cursor = 0
    source_label_tables = []
    for data in datasets:
        source_labels = data["labels"].astype(str).tolist()
        source_label_tables.append(source_labels)
        count = len(data["y"])
        for start in range(0, count, args.chunk_size):
            stop = min(count, start + args.chunk_size)
            destination = slice(cursor + start, cursor + stop)
            outputs["x"][destination] = data["x"][start:stop]
            outputs["y"][destination] = remap_targets(
                data["y"][start:stop], source_labels, labels
            )
            outputs["subjects"][destination] = data["subjects"][start:stop].astype(str)
            outputs["clips"][destination] = data["clips"][start:stop].astype(str)
        cursor += count
    for array in outputs.values():
        array.flush()

    metadata = {
        "format": "pose-windows-v1",
        "samples": total,
        "sample_shape": list(sample_shape),
        "labels": labels,
        "sources": [str(path.resolve()) for path in args.inputs],
        "source_label_tables": source_label_tables,
    }
    (args.output / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    print(f"merged {len(datasets)} inputs and {total} samples into {args.output}")


if __name__ == "__main__":
    main()

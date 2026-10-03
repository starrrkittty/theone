"""Merge compatible memory-mapped pose-window datasets without loading them into RAM."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from dataset_io import load_dataset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chunk-size", type=int, default=1024)
    args = parser.parse_args()

    datasets = [load_dataset(path, mmap_mode="r") for path in args.inputs]
    labels = datasets[0]["labels"].astype(str).tolist()
    sample_shape = tuple(datasets[0]["x"].shape[1:])
    for path, data in zip(args.inputs, datasets):
        if data["labels"].astype(str).tolist() != labels:
            raise ValueError(f"Label order differs in {path}")
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
    for data in datasets:
        count = len(data["y"])
        for start in range(0, count, args.chunk_size):
            stop = min(count, start + args.chunk_size)
            destination = slice(cursor + start, cursor + stop)
            outputs["x"][destination] = data["x"][start:stop]
            outputs["y"][destination] = data["y"][start:stop]
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
    }
    (args.output / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    print(f"merged {len(datasets)} inputs and {total} samples into {args.output}")


if __name__ == "__main__":
    main()

"""Filter pose-window labels without loading an entire dataset into memory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

try:
    from .dataset_io import load_dataset
except ImportError:  # Direct script execution
    from dataset_io import load_dataset


def filter_dataset(
    input_path: Path,
    output_path: Path,
    excluded_labels: set[str],
    chunk_size: int = 1024,
) -> dict:
    data = load_dataset(input_path, mmap_mode="r")
    source_labels = data["labels"].astype(str).tolist()
    unknown = sorted(excluded_labels.difference(source_labels))
    if unknown:
        raise ValueError(f"Excluded labels are absent from the dataset: {unknown}")

    kept_labels = [label for label in source_labels if label not in excluded_labels]
    if not kept_labels:
        raise ValueError("Filtering would remove every label")

    old_to_new = np.full(len(source_labels), -1, dtype=np.int64)
    for new_index, label in enumerate(kept_labels):
        old_to_new[source_labels.index(label)] = new_index

    source_targets = np.asarray(data["y"], dtype=np.int64)
    keep_mask = old_to_new[source_targets] >= 0
    source_indices = np.flatnonzero(keep_mask)
    sample_shape = tuple(data["x"].shape[1:])
    max_subject = max(map(len, data["subjects"].astype(str)))
    max_clip = max(map(len, data["clips"].astype(str)))

    output_path.mkdir(parents=True, exist_ok=True)
    outputs = {
        "x": np.lib.format.open_memmap(
            output_path / "x.npy",
            mode="w+",
            dtype=np.float32,
            shape=(len(source_indices), *sample_shape),
        ),
        "y": np.lib.format.open_memmap(
            output_path / "y.npy", mode="w+", dtype=np.int64, shape=(len(source_indices),)
        ),
        "subjects": np.lib.format.open_memmap(
            output_path / "subjects.npy",
            mode="w+",
            dtype=f"<U{max_subject}",
            shape=(len(source_indices),),
        ),
        "clips": np.lib.format.open_memmap(
            output_path / "clips.npy",
            mode="w+",
            dtype=f"<U{max_clip}",
            shape=(len(source_indices),),
        ),
    }

    for destination_start in range(0, len(source_indices), chunk_size):
        destination_stop = min(len(source_indices), destination_start + chunk_size)
        selected = source_indices[destination_start:destination_stop]
        destination = slice(destination_start, destination_stop)
        outputs["x"][destination] = data["x"][selected]
        outputs["y"][destination] = old_to_new[source_targets[selected]]
        outputs["subjects"][destination] = data["subjects"][selected].astype(str)
        outputs["clips"][destination] = data["clips"][selected].astype(str)
    for array in outputs.values():
        array.flush()

    metadata = {
        "format": "pose-windows-v1",
        "samples": len(source_indices),
        "sample_shape": list(sample_shape),
        "labels": kept_labels,
        "source": str(input_path.resolve()),
        "excluded_labels": sorted(excluded_labels),
    }
    (output_path / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exclude", nargs="+", required=True)
    parser.add_argument("--chunk-size", type=int, default=1024)
    args = parser.parse_args()
    metadata = filter_dataset(
        args.input, args.output, set(args.exclude), chunk_size=args.chunk_size
    )
    print(
        f"saved {metadata['samples']} windows and {len(metadata['labels'])} labels "
        f"to {args.output.resolve()}"
    )


if __name__ == "__main__":
    main()

"""Remap pose-window labels while preserving samples and split identities."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

try:
    from .dataset_io import load_dataset
except ImportError:  # Direct script execution
    from dataset_io import load_dataset


def remap_dataset(
    input_path: Path,
    output_path: Path,
    label_mapping: dict[str, str],
    chunk_size: int = 1024,
) -> dict:
    data = load_dataset(input_path, mmap_mode="r")
    source_labels = data["labels"].astype(str).tolist()
    missing = sorted(set(label_mapping).difference(source_labels))
    if missing:
        raise ValueError(f"Mapped source labels are absent from the dataset: {missing}")
    if any(not value.strip() for value in label_mapping.values()):
        raise ValueError("Mapped labels must be non-empty")

    destination_for_source = [label_mapping.get(label, label) for label in source_labels]
    destination_labels = list(dict.fromkeys(destination_for_source))
    old_to_new = np.asarray(
        [destination_labels.index(label) for label in destination_for_source],
        dtype=np.int64,
    )
    targets = np.asarray(data["y"], dtype=np.int64)
    sample_shape = tuple(data["x"].shape[1:])
    max_subject = max(map(len, data["subjects"].astype(str)))
    max_clip = max(map(len, data["clips"].astype(str)))

    output_path.mkdir(parents=True, exist_ok=True)
    outputs = {
        "x": np.lib.format.open_memmap(
            output_path / "x.npy",
            mode="w+",
            dtype=np.float32,
            shape=(len(targets), *sample_shape),
        ),
        "y": np.lib.format.open_memmap(
            output_path / "y.npy", mode="w+", dtype=np.int64, shape=(len(targets),)
        ),
        "subjects": np.lib.format.open_memmap(
            output_path / "subjects.npy",
            mode="w+",
            dtype=f"<U{max_subject}",
            shape=(len(targets),),
        ),
        "clips": np.lib.format.open_memmap(
            output_path / "clips.npy",
            mode="w+",
            dtype=f"<U{max_clip}",
            shape=(len(targets),),
        ),
    }
    for start in range(0, len(targets), chunk_size):
        stop = min(len(targets), start + chunk_size)
        selected = slice(start, stop)
        outputs["x"][selected] = data["x"][selected]
        outputs["y"][selected] = old_to_new[targets[selected]]
        outputs["subjects"][selected] = data["subjects"][selected].astype(str)
        outputs["clips"][selected] = data["clips"][selected].astype(str)
    for array in outputs.values():
        array.flush()

    metadata = {
        "format": "pose-windows-v1",
        "samples": len(targets),
        "sample_shape": list(sample_shape),
        "labels": destination_labels,
        "source": str(input_path.resolve()),
        "label_mapping": label_mapping,
    }
    (output_path / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label-map", type=Path, required=True)
    parser.add_argument("--chunk-size", type=int, default=1024)
    args = parser.parse_args()
    mapping = json.loads(args.label_map.read_text(encoding="utf-8"))
    if not isinstance(mapping, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in mapping.items()
    ):
        raise ValueError("Label map must be a JSON object of string-to-string mappings")
    metadata = remap_dataset(args.input, args.output, mapping, args.chunk_size)
    print(
        f"saved {metadata['samples']} windows with {len(metadata['labels'])} labels "
        f"to {args.output.resolve()}"
    )


if __name__ == "__main__":
    main()

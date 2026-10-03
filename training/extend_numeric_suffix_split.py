"""Extend a leakage-aware split with subjects ending in an official clip number."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

try:
    from .dataset_io import load_dataset
except ImportError:  # Direct script execution
    from dataset_io import load_dataset


SPLIT_NAMES = ("train", "validation", "test")


def extend_split(
    base: dict[str, list[str]],
    subjects: list[str],
    train_max: int,
    validation_numbers: set[int],
    test_numbers: set[int],
) -> dict[str, list[str]]:
    result = {name: list(base.get(name, [])) for name in SPLIT_NAMES}
    existing_locations: dict[str, str] = {}
    for name in SPLIT_NAMES:
        for subject in result[name]:
            previous = existing_locations.setdefault(subject, name)
            if previous != name:
                raise ValueError(f"Subject {subject!r} appears in both {previous} and {name}")
    for subject in sorted(set(subjects)):
        if subject in existing_locations:
            continue
        match = re.search(r"_(\d+)$", subject)
        if not match:
            raise ValueError(f"New subject has no numeric suffix: {subject!r}")
        number = int(match.group(1))
        if number <= train_max:
            destination = "train"
        elif number in validation_numbers:
            destination = "validation"
        elif number in test_numbers:
            destination = "test"
        else:
            raise ValueError(f"No split rule for subject {subject!r}")
        result[destination].append(subject)
        existing_locations[subject] = destination
    return {name: sorted(set(result[name])) for name in SPLIT_NAMES}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-split", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train-max", type=int, default=15)
    parser.add_argument("--validation-numbers", type=int, nargs="+", default=[16])
    parser.add_argument("--test-numbers", type=int, nargs="+", default=[17, 18, 19])
    args = parser.parse_args()

    base = json.loads(args.base_split.read_text(encoding="utf-8"))
    data = load_dataset(args.dataset, mmap_mode="r")
    result = extend_split(
        base,
        data["subjects"].astype(str).tolist(),
        args.train_max,
        set(args.validation_numbers),
        set(args.test_numbers),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        "split subjects: "
        + ", ".join(f"{name}={len(result[name])}" for name in SPLIT_NAMES)
    )
    print(f"saved to {args.output.resolve()}")


if __name__ == "__main__":
    main()

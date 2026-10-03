"""Evaluate a saved browser ST-GCN checkpoint on another pose-window domain."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

try:
    from .dataset_io import load_dataset
    from .train_stgcn import (
        BrowserSTGCN,
        WindowDataset,
        choose_device,
        classification_metrics,
        evaluate,
        plot_confusion,
    )
except ImportError:  # Direct script execution
    from dataset_io import load_dataset
    from train_stgcn import (
        BrowserSTGCN,
        WindowDataset,
        choose_device,
        classification_metrics,
        evaluate,
        plot_confusion,
    )


def remap_evaluation_targets(
    targets: np.ndarray,
    dataset_labels: list[str],
    model_labels: list[str],
    indices: np.ndarray,
    include_labels: list[str] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Filter to shared labels and remap dataset target ids to model ids."""
    if len(dataset_labels) != len(set(dataset_labels)) or len(model_labels) != len(set(model_labels)):
        raise ValueError("Dataset and model label tables must not contain duplicates")
    allowed = set(include_labels or model_labels)
    unknown_requested = allowed - set(dataset_labels)
    if unknown_requested:
        raise ValueError(f"Requested labels missing from dataset: {sorted(unknown_requested)}")
    unknown_model = allowed - set(model_labels)
    if unknown_model:
        raise ValueError(f"Requested labels missing from model: {sorted(unknown_model)}")
    model_index = {label: index for index, label in enumerate(model_labels)}
    selected: list[int] = []
    remapped = np.full(len(targets), -1, dtype=np.int64)
    for index in indices:
        target = int(targets[index])
        if target < 0 or target >= len(dataset_labels):
            raise ValueError(f"Dataset target {target} is outside its label table")
        label = dataset_labels[target]
        if label in allowed and label in model_index:
            selected.append(int(index))
            remapped[index] = model_index[label]
    if not selected:
        raise ValueError("No samples remain after label remapping")
    return np.asarray(selected, dtype=np.int64), remapped


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda", "xpu"])
    parser.add_argument("--dataloader-workers", type=int, default=0)
    parser.add_argument("--cpu-threads", type=int, default=0)
    parser.add_argument("--subjects", nargs="*", default=[])
    parser.add_argument(
        "--allow-label-remap",
        action="store_true",
        help="Evaluate shared labels by name when dataset/model label tables differ.",
    )
    parser.add_argument(
        "--include-labels",
        nargs="*",
        help="Optional subset of shared labels to evaluate.",
    )
    args = parser.parse_args()

    data = load_dataset(args.dataset, mmap_mode="r")
    dataset_labels = data["labels"].astype(str).tolist()
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    model_labels = [str(label) for label in checkpoint["labels"]]
    if dataset_labels != model_labels and not args.allow_label_remap:
        raise ValueError(
            "Dataset/checkpoint label order differs. "
            "Use --allow-label-remap only for an intentional shared-label evaluation. "
            f"dataset={dataset_labels}, checkpoint={model_labels}"
        )

    x = data["x"]
    y = np.asarray(data["y"], dtype=np.int64)
    if args.subjects:
        selected = set(args.subjects)
        subjects = data["subjects"].astype(str)
        indices = np.asarray(
            [index for index, subject in enumerate(subjects) if subject in selected],
            dtype=np.int64,
        )
        if len(indices) == 0:
            raise ValueError(f"No samples found for subjects: {sorted(selected)}")
    else:
        indices = np.arange(len(y), dtype=np.int64)
    if dataset_labels != model_labels or args.include_labels:
        indices, y = remap_evaluation_targets(
            y,
            dataset_labels,
            model_labels,
            indices,
            args.include_labels,
        )
    coordinate_mode = str(checkpoint.get("coordinate_mode", "xyz"))
    dataset = WindowDataset(
        x,
        y,
        indices,
        np.asarray(checkpoint["mean"], dtype=np.float32),
        np.asarray(checkpoint["std"], dtype=np.float32),
        coordinate_mode,
    )
    loader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.dataloader_workers,
        persistent_workers=args.dataloader_workers > 0,
    )
    device = choose_device(args.device)
    if device.type == "cpu":
        torch.set_num_threads(args.cpu_threads or min(8, max(1, torch.get_num_threads())))
    model = BrowserSTGCN(len(model_labels), np.asarray(checkpoint["graph"], dtype=np.float32))
    model.load_state_dict(checkpoint["state_dict"])
    model.to(device)
    loss, accuracy, confusion = evaluate(model, loader, device, len(model_labels))
    report = {
        "dataset": str(args.dataset.resolve()),
        "checkpoint": str(args.checkpoint.resolve()),
        "samples": int(len(indices)),
        "subjects": sorted(args.subjects),
        "dataset_labels": dataset_labels,
        "model_labels": model_labels,
        "included_labels": args.include_labels or sorted(set(dataset_labels) & set(model_labels)),
        "coordinate_mode": coordinate_mode,
        "loss": loss,
        "accuracy": accuracy,
        "metrics": classification_metrics(confusion, model_labels),
        "confusion_matrix": confusion.tolist(),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "evaluation_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    plot_confusion(confusion, model_labels, args.output_dir)
    print(f"samples={len(indices)} accuracy={accuracy:.3f}")
    print(f"artifacts saved to {args.output_dir}")


if __name__ == "__main__":
    main()

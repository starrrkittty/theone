"""Evaluate a saved browser ST-GCN checkpoint on another pose-window domain."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from dataset_io import load_dataset
from train_stgcn import (
    BrowserSTGCN,
    WindowDataset,
    choose_device,
    classification_metrics,
    evaluate,
    plot_confusion,
)


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
    args = parser.parse_args()

    data = load_dataset(args.dataset, mmap_mode="r")
    labels = data["labels"].astype(str).tolist()
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    model_labels = [str(label) for label in checkpoint["labels"]]
    if labels != model_labels:
        raise ValueError(
            "Dataset/checkpoint label order differs. "
            f"dataset={labels}, checkpoint={model_labels}"
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
    model = BrowserSTGCN(len(labels), np.asarray(checkpoint["graph"], dtype=np.float32))
    model.load_state_dict(checkpoint["state_dict"])
    model.to(device)
    loss, accuracy, confusion = evaluate(model, loader, device, len(labels))
    report = {
        "dataset": str(args.dataset.resolve()),
        "checkpoint": str(args.checkpoint.resolve()),
        "samples": int(len(indices)),
        "subjects": sorted(args.subjects),
        "labels": labels,
        "coordinate_mode": coordinate_mode,
        "loss": loss,
        "accuracy": accuracy,
        "metrics": classification_metrics(confusion, labels),
        "confusion_matrix": confusion.tolist(),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "evaluation_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    plot_confusion(confusion, labels, args.output_dir)
    print(f"samples={len(indices)} accuracy={accuracy:.3f}")
    print(f"artifacts saved to {args.output_dir}")


if __name__ == "__main__":
    main()

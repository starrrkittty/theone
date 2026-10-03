"""Evaluate runtime semantic thresholds on an independent pose-window dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

try:
    from .calibrate_semantic_threshold import threshold_metrics
    from .dataset_io import load_dataset
    from .evaluate_stgcn import remap_evaluation_targets
    from .train_stgcn import BrowserSTGCN, WindowDataset, choose_device, plot_confusion
except ImportError:  # Direct script execution
    from calibrate_semantic_threshold import threshold_metrics
    from dataset_io import load_dataset
    from evaluate_stgcn import remap_evaluation_targets
    from train_stgcn import BrowserSTGCN, WindowDataset, choose_device, plot_confusion


def load_threshold_configuration(path: Path) -> tuple[dict[str, float], str]:
    """Load per-class thresholds from a calibration report or deployed model card."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "per_class_thresholds" in payload:
        raw = payload["per_class_thresholds"]
        source_key = "per_class_thresholds"
    elif "semantic_thresholds" in payload:
        raw = payload["semantic_thresholds"]
        source_key = "semantic_thresholds"
    else:
        raise ValueError(
            "Threshold JSON must contain per_class_thresholds or semantic_thresholds"
        )
    if not isinstance(raw, dict) or not raw:
        raise ValueError(f"{source_key} must be a non-empty object")
    thresholds: dict[str, float] = {}
    for label, value in raw.items():
        threshold = float(value)
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"Threshold for {label!r} is outside [0, 1]: {threshold}")
        thresholds[str(label)] = threshold
    return thresholds, source_key


def apply_threshold_overrides(
    thresholds: dict[str, float], overrides: list[str]
) -> dict[str, float]:
    result = dict(thresholds)
    for item in overrides:
        if "=" not in item:
            raise ValueError(f"Threshold override must be LABEL=VALUE: {item!r}")
        label, raw_value = item.split("=", 1)
        if label not in result:
            raise ValueError(f"Threshold override label is not configured: {label!r}")
        value = float(raw_value)
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"Threshold override for {label!r} is outside [0, 1]: {value}")
        result[label] = value
    return result


def probabilities_for_indices(
    data: dict[str, np.ndarray],
    targets: np.ndarray,
    indices: np.ndarray,
    checkpoint: dict,
    batch_size: int,
    device: torch.device,
    dataloader_workers: int,
) -> tuple[np.ndarray, np.ndarray]:
    dataset = WindowDataset(
        data["x"],
        targets,
        indices,
        np.asarray(checkpoint["mean"], dtype=np.float32),
        np.asarray(checkpoint["std"], dtype=np.float32),
        str(checkpoint.get("coordinate_mode", "xyz")),
    )
    loader = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=dataloader_workers,
        persistent_workers=dataloader_workers > 0,
    )
    labels = [str(label) for label in checkpoint["labels"]]
    model = BrowserSTGCN(len(labels), np.asarray(checkpoint["graph"], dtype=np.float32))
    model.load_state_dict(checkpoint["state_dict"])
    model.to(device)
    model.eval()
    probabilities: list[np.ndarray] = []
    truths: list[np.ndarray] = []
    with torch.no_grad():
        for x, y in loader:
            probabilities.append(torch.softmax(model(x.to(device)), dim=1).cpu().numpy())
            truths.append(y.numpy())
    return np.concatenate(probabilities), np.concatenate(truths)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--thresholds-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--subjects", nargs="*", default=[])
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda", "xpu"])
    parser.add_argument("--cpu-threads", type=int, default=0)
    parser.add_argument("--dataloader-workers", type=int, default=0)
    parser.add_argument(
        "--override-threshold",
        action="append",
        default=[],
        metavar="LABEL=VALUE",
        help="Temporarily override one calibrated threshold for an ablation.",
    )
    args = parser.parse_args()

    data = load_dataset(args.dataset, mmap_mode="r")
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    dataset_labels = data["labels"].astype(str).tolist()
    model_labels = [str(label) for label in checkpoint["labels"]]
    thresholds, threshold_source_key = load_threshold_configuration(args.thresholds_json)
    thresholds = apply_threshold_overrides(thresholds, args.override_threshold)
    semantic_labels = list(thresholds)
    missing_model = sorted(set(semantic_labels) - set(model_labels))
    if missing_model:
        raise ValueError(f"Threshold labels missing from model: {missing_model}")
    included_labels = [*semantic_labels, "unknown"]
    missing_dataset = sorted(set(included_labels) - set(dataset_labels))
    if missing_dataset:
        raise ValueError(f"Evaluation labels missing from dataset: {missing_dataset}")

    targets = np.asarray(data["y"], dtype=np.int64)
    if args.subjects:
        selected_subjects = set(args.subjects)
        subjects = data["subjects"].astype(str)
        candidate_indices = np.asarray(
            [index for index, subject in enumerate(subjects) if subject in selected_subjects],
            dtype=np.int64,
        )
        if len(candidate_indices) == 0:
            raise ValueError(f"No samples found for subjects: {sorted(selected_subjects)}")
    else:
        candidate_indices = np.arange(len(targets), dtype=np.int64)
    indices, remapped_targets = remap_evaluation_targets(
        targets,
        dataset_labels,
        model_labels,
        candidate_indices,
        included_labels,
    )

    device = choose_device(args.device)
    if device.type == "cpu":
        torch.set_num_threads(args.cpu_threads or min(8, max(1, torch.get_num_threads())))
    probabilities, truths = probabilities_for_indices(
        data,
        remapped_targets,
        indices,
        checkpoint,
        args.batch_size,
        device,
        args.dataloader_workers,
    )
    metrics = threshold_metrics(
        probabilities,
        truths,
        model_labels,
        semantic_labels,
        thresholds,
    )
    report = {
        "dataset": str(args.dataset.resolve()),
        "checkpoint": str(args.checkpoint.resolve()),
        "thresholds_json": str(args.thresholds_json.resolve()),
        "threshold_source_key": threshold_source_key,
        "threshold_overrides": args.override_threshold,
        "subjects": sorted(args.subjects),
        "dataset_labels": dataset_labels,
        "model_labels": model_labels,
        "semantic_labels": semantic_labels,
        "samples": int(len(indices)),
        "device": str(device),
        "metrics": metrics,
        "note": (
            "Applies the same per-class single-window confidence gate as runtime; "
            "the runtime two-consecutive-hit confirmation is not simulated."
        ),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "semantic_threshold_evaluation.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    plot_confusion(
        np.asarray(metrics["confusion_matrix"], dtype=np.int64),
        included_labels,
        args.output_dir,
    )
    print(
        f"samples={len(indices)} balanced_accuracy={metrics['balanced_accuracy']:.3f} "
        f"unknown_far={metrics['unknown_false_accept_rate']:.3f} "
        f"acceptance_rate={metrics['acceptance_rate']:.3f}"
    )
    print(f"artifacts saved to {args.output_dir}")


if __name__ == "__main__":
    main()

"""Calibrate long-tail semantic routing without using the held-out test person."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import torch
from torch.utils.data import DataLoader

try:
    from .dataset_io import load_dataset
    from .train_stgcn import (
        BrowserSTGCN,
        WindowDataset,
        classification_metrics,
        load_split_file,
    )
except ImportError:  # Direct script execution
    from dataset_io import load_dataset
    from train_stgcn import (
        BrowserSTGCN,
        WindowDataset,
        classification_metrics,
        load_split_file,
    )


DEFAULT_CORE_LABELS = [
    "squat",
    "pushup",
    "plank",
    "bicep_curl",
    "alternate_bicep_curl",
]


def probabilities_for_subjects(data, checkpoint, selected_subjects, batch_size):
    subjects = data["subjects"].astype(str)
    selected = set(selected_subjects)
    indices = np.asarray(
        [index for index, subject in enumerate(subjects) if subject in selected],
        dtype=np.int64,
    )
    if len(indices) == 0:
        raise ValueError(f"No samples found for subjects: {sorted(selected)}")
    dataset = WindowDataset(
        data["x"],
        data["y"],
        indices,
        np.asarray(checkpoint["mean"], dtype=np.float32),
        np.asarray(checkpoint["std"], dtype=np.float32),
        str(checkpoint.get("coordinate_mode", "xyz")),
    )
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False, num_workers=0)
    labels = [str(label) for label in checkpoint["labels"]]
    model = BrowserSTGCN(len(labels), np.asarray(checkpoint["graph"], dtype=np.float32))
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    probabilities: list[np.ndarray] = []
    truths: list[np.ndarray] = []
    with torch.no_grad():
        for x, y in loader:
            probabilities.append(torch.softmax(model(x), dim=1).numpy())
            truths.append(y.numpy())
    return np.concatenate(probabilities), np.concatenate(truths)


def threshold_metrics(probabilities, truths, labels, semantic_labels, threshold):
    output_labels = [*semantic_labels, "unknown"]
    output_index = {label: index for index, label in enumerate(output_labels)}
    model_index = {label: index for index, label in enumerate(labels)}
    semantic_indices = [model_index[label] for label in semantic_labels]
    confusion = np.zeros((len(output_labels), len(output_labels)), dtype=np.int64)
    accepted = 0
    considered = 0
    for scores, truth_index in zip(probabilities, truths):
        truth = labels[int(truth_index)]
        if truth not in output_index:
            continue
        considered += 1
        relative = int(np.argmax(scores[semantic_indices]))
        predicted_label = semantic_labels[relative]
        confidence = float(scores[semantic_indices[relative]])
        required = threshold[predicted_label] if isinstance(threshold, dict) else threshold
        if confidence < required:
            predicted_label = "unknown"
        else:
            accepted += 1
        confusion[output_index[truth], output_index[predicted_label]] += 1
    metrics = classification_metrics(confusion, output_labels)
    metrics["threshold"] = threshold
    metrics["considered_samples"] = considered
    metrics["accepted_samples"] = accepted
    metrics["acceptance_rate"] = accepted / considered if considered else 0.0
    metrics["confusion_matrix"] = confusion.tolist()
    return metrics


def calibrate_class_thresholds(
    probabilities,
    truths,
    labels,
    semantic_labels,
    thresholds,
    min_precision,
    max_unknown_far,
):
    model_index = {label: index for index, label in enumerate(labels)}
    semantic_indices = [model_index[label] for label in semantic_labels]
    truth_labels = np.asarray([labels[int(index)] for index in truths])
    semantic_scores = probabilities[:, semantic_indices]
    top_relative = semantic_scores.argmax(axis=1)
    top_labels = np.asarray([semantic_labels[index] for index in top_relative])
    top_scores = semantic_scores[np.arange(len(semantic_scores)), top_relative]
    unknown_total = max(1, int((truth_labels == "unknown").sum()))
    selected: dict[str, float] = {}
    diagnostics: dict[str, dict[str, float | bool]] = {}
    for label in semantic_labels:
        candidates = []
        for threshold in thresholds:
            predicted = (top_labels == label) & (top_scores >= threshold)
            truth_positive = truth_labels == label
            tp = int((predicted & truth_positive).sum())
            fp = int((predicted & ~truth_positive).sum())
            fn = int((~predicted & truth_positive).sum())
            precision = tp / (tp + fp) if tp + fp else 0.0
            recall = tp / (tp + fn) if tp + fn else 0.0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
            unknown_fp = int((predicted & (truth_labels == "unknown")).sum())
            candidates.append(
                {
                    "threshold": float(threshold),
                    "precision": precision,
                    "recall": recall,
                    "f1": f1,
                    "unknown_false_accept_rate": unknown_fp / unknown_total,
                }
            )
        eligible = [
            item
            for item in candidates
            if item["precision"] >= min_precision
            and item["unknown_false_accept_rate"] <= max_unknown_far
        ]
        if eligible:
            choice = max(eligible, key=lambda item: (item["f1"], item["recall"]))
            satisfied = True
        else:
            choice = max(
                candidates,
                key=lambda item: (
                    item["f1"],
                    item["precision"],
                    -item["unknown_false_accept_rate"],
                ),
            )
            satisfied = False
        selected[label] = float(choice["threshold"])
        diagnostics[label] = {**choice, "constraints_satisfied": satisfied}
    return selected, diagnostics


def enforce_global_unknown_limit(
    probabilities,
    truths,
    labels,
    semantic_labels,
    thresholds,
    class_thresholds,
    maximum_unknown_far,
):
    selected = dict(class_thresholds)
    current = threshold_metrics(
        probabilities, truths, labels, semantic_labels, selected
    )
    while current["unknown_false_accept_rate"] > maximum_unknown_far:
        candidates = []
        for label in semantic_labels:
            higher = thresholds[thresholds > selected[label]]
            for higher_threshold in higher:
                proposal = dict(selected)
                proposal[label] = float(higher_threshold)
                metrics = threshold_metrics(
                    probabilities, truths, labels, semantic_labels, proposal
                )
                reduction = (
                    current["unknown_false_accept_rate"]
                    - metrics["unknown_false_accept_rate"]
                )
                if reduction <= 0:
                    continue
                balanced_loss = current["balanced_accuracy"] - metrics["balanced_accuracy"]
                candidates.append(
                    (
                        balanced_loss / reduction,
                        -metrics["balanced_accuracy"],
                        label,
                        proposal,
                        metrics,
                    )
                )
        if not candidates:
            break
        _, _, _, selected, current = min(candidates, key=lambda item: item[:3])
    return selected, current


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--validation-subjects", nargs="+")
    parser.add_argument("--test-subjects", nargs="+")
    parser.add_argument(
        "--split-file", type=Path,
        help="Use validation and test subject lists from a training split JSON.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--max-validation-unknown-far", type=float, default=0.10)
    parser.add_argument("--per-class-min-precision", type=float, default=0.85)
    parser.add_argument("--per-class-max-unknown-far", type=float, default=0.03)
    parser.add_argument("--minimum-runtime-threshold", type=float, default=0.72)
    parser.add_argument("--core-labels", nargs="*", default=DEFAULT_CORE_LABELS)
    args = parser.parse_args()

    if args.split_file:
        if args.validation_subjects or args.test_subjects:
            raise ValueError("Use either --split-file or subject arguments, not both")
        _, validation_subjects, test_subjects = load_split_file(args.split_file.resolve())
    else:
        if not args.validation_subjects or not args.test_subjects:
            raise ValueError("Provide --split-file or both validation/test subjects")
        validation_subjects = args.validation_subjects
        test_subjects = args.test_subjects

    data = load_dataset(args.dataset, mmap_mode="r")
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    labels = [str(label) for label in checkpoint["labels"]]
    if data["labels"].astype(str).tolist() != labels:
        raise ValueError("Dataset and checkpoint label order differs")
    semantic_labels = [
        label for label in labels if label not in set(args.core_labels) | {"unknown"}
    ]

    validation_probs, validation_truths = probabilities_for_subjects(
        data, checkpoint, validation_subjects, args.batch_size
    )
    test_probs, test_truths = probabilities_for_subjects(
        data, checkpoint, test_subjects, args.batch_size
    )
    thresholds = np.concatenate(
        (np.round(np.arange(0.50, 0.951, 0.01), 2), np.asarray([0.97, 0.98, 0.99, 0.995, 0.999]))
    )
    thresholds = thresholds[thresholds >= args.minimum_runtime_threshold]
    curve = [
        threshold_metrics(
            validation_probs,
            validation_truths,
            labels,
            semantic_labels,
            float(threshold),
        )
        for threshold in thresholds
    ]
    eligible = [
        item
        for item in curve
        if item.get("unknown_false_accept_rate") is not None
        and item["unknown_false_accept_rate"] <= args.max_validation_unknown_far
    ]
    if eligible:
        selected = max(
            eligible,
            key=lambda item: (
                item["balanced_accuracy"],
                -item["unknown_false_accept_rate"],
                item["acceptance_rate"],
            ),
        )
    else:
        selected = min(
            curve,
            key=lambda item: (
                item["unknown_false_accept_rate"],
                -item["balanced_accuracy"],
            ),
        )
    threshold = float(selected["threshold"])
    test_metrics = threshold_metrics(
        test_probs, test_truths, labels, semantic_labels, threshold
    )
    class_thresholds, class_diagnostics = calibrate_class_thresholds(
        validation_probs,
        validation_truths,
        labels,
        semantic_labels,
        thresholds,
        args.per_class_min_precision,
        args.per_class_max_unknown_far,
    )
    raw_class_thresholds = dict(class_thresholds)
    class_thresholds, validation_class_metrics = enforce_global_unknown_limit(
        validation_probs,
        validation_truths,
        labels,
        semantic_labels,
        thresholds,
        class_thresholds,
        args.max_validation_unknown_far,
    )
    test_class_metrics = threshold_metrics(
        test_probs,
        test_truths,
        labels,
        semantic_labels,
        class_thresholds,
    )
    report = {
        "dataset": str(args.dataset.resolve()),
        "checkpoint": str(args.checkpoint.resolve()),
        "semantic_labels": semantic_labels,
        "core_labels_excluded": args.core_labels,
        "validation_subjects": validation_subjects,
        "test_subjects": test_subjects,
        "split_file": str(args.split_file.resolve()) if args.split_file else None,
        "max_validation_unknown_false_accept_rate": args.max_validation_unknown_far,
        "validation_constraint_satisfied": bool(eligible),
        "selected_threshold": threshold,
        "validation": selected,
        "test": test_metrics,
        "raw_per_class_thresholds": raw_class_thresholds,
        "per_class_thresholds": class_thresholds,
        "per_class_validation_diagnostics": class_diagnostics,
        "validation_with_per_class_thresholds": validation_class_metrics,
        "test_with_per_class_thresholds": test_class_metrics,
        "validation_curve": curve,
        "note": "Two consecutive hits in the runtime tracker are an additional guard not simulated here.",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "semantic_calibration_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(
        thresholds,
        [item["balanced_accuracy"] for item in curve],
        label="validation balanced accuracy",
    )
    ax.plot(
        thresholds,
        [item["unknown_false_accept_rate"] for item in curve],
        label="validation unknown false accept",
    )
    ax.axvline(threshold, color="black", linestyle="--", label=f"selected {threshold:.2f}")
    ax.set_xlabel("Semantic confidence threshold")
    ax.set_ylim(0, 1)
    ax.legend()
    fig.tight_layout()
    fig.savefig(args.output_dir / "semantic_threshold_curve.png", dpi=160)
    plt.close(fig)
    print(
        f"selected_threshold={threshold:.2f} "
        f"validation_balanced={selected['balanced_accuracy']:.3f} "
        f"validation_unknown_far={selected['unknown_false_accept_rate']:.3f}"
    )
    if not eligible:
        print("warning=no threshold satisfied the validation unknown false-accept limit")
    print(
        f"test_balanced={test_metrics['balanced_accuracy']:.3f} "
        f"test_unknown_far={test_metrics['unknown_false_accept_rate']:.3f}"
    )
    print(
        "per_class_test_balanced="
        f"{test_class_metrics['balanced_accuracy']:.3f} "
        "per_class_test_unknown_far="
        f"{test_class_metrics['unknown_false_accept_rate']:.3f}"
    )


if __name__ == "__main__":
    main()

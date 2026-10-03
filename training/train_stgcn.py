"""Train the browser-compatible lightweight ST-GCN and export JSON weights."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset

from dataset_io import load_dataset


HIDDEN = 64
N_JOINTS = 17
COORD_DIM = 3
TEMPORAL_POOLING = "mean_std_velocity_range"
TEMPORAL_STATS = 4


class WindowDataset(Dataset):
    """Normalize memory-mapped windows one sample at a time."""

    def __init__(
        self,
        x,
        y,
        indices: np.ndarray,
        mean: np.ndarray,
        std: np.ndarray,
        coordinate_mode: str,
    ):
        self.x = x
        self.y = y
        self.indices = indices
        self.mean = mean.astype(np.float32)
        self.std = std.astype(np.float32)
        self.coordinate_mode = coordinate_mode

    def __len__(self):
        return len(self.indices)

    def __getitem__(self, item):
        index = int(self.indices[item])
        sample = np.asarray(self.x[index], dtype=np.float32).copy()
        if self.coordinate_mode == "xy":
            sample[..., 2] = 0.0
        sample = (sample - self.mean) / self.std
        return torch.from_numpy(sample), torch.tensor(int(self.y[index]), dtype=torch.long)


def streaming_mean_std(
    x,
    indices: np.ndarray,
    coordinate_mode: str,
    chunk_size: int = 1024,
):
    total = 0
    sum_values = np.zeros((N_JOINTS, COORD_DIM), dtype=np.float64)
    sum_squares = np.zeros((N_JOINTS, COORD_DIM), dtype=np.float64)
    for start in range(0, len(indices), chunk_size):
        chunk = np.asarray(x[indices[start:start + chunk_size]], dtype=np.float32).copy()
        if coordinate_mode == "xy":
            chunk[..., 2] = 0.0
        sum_values += chunk.sum(axis=(0, 1), dtype=np.float64)
        sum_squares += np.square(chunk, dtype=np.float64).sum(axis=(0, 1))
        total += chunk.shape[0] * chunk.shape[1]
    if total == 0:
        raise ValueError("Training split contains no samples")
    mean = sum_values / total
    variance = np.maximum(sum_squares / total - np.square(mean), 0.0)
    std = np.sqrt(variance)
    std = np.where(std < 1e-6, 1.0, std)
    return mean.astype(np.float32), std.astype(np.float32)


def choose_device(requested: str) -> torch.device:
    if requested != "auto":
        return torch.device(requested)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        return torch.device("xpu")
    return torch.device("cpu")


def adjacency() -> np.ndarray:
    edges = [
        (0, 1), (0, 2), (2, 4), (1, 3), (3, 5),
        (0, 6), (1, 7), (6, 7), (6, 8), (8, 10),
        (7, 9), (9, 11), (12, 13), (12, 14), (12, 15),
        (12, 16), (13, 15), (14, 16),
    ]
    matrix = np.eye(N_JOINTS, dtype=np.float32)
    for left, right in edges:
        matrix[left, right] = 1.0
        matrix[right, left] = 1.0
    degree = matrix.sum(axis=1)
    inv_sqrt = np.diag(1.0 / np.sqrt(np.maximum(degree, 1e-8)))
    return (inv_sqrt @ matrix @ inv_sqrt).astype(np.float32)


class BrowserSTGCN(nn.Module):
    def __init__(self, n_classes: int, graph: np.ndarray):
        super().__init__()
        self.register_buffer("graph", torch.tensor(graph))
        self.gc1_w = nn.Parameter(torch.empty(COORD_DIM, HIDDEN))
        self.gc1_b = nn.Parameter(torch.zeros(N_JOINTS, HIDDEN))
        self.gc2_w = nn.Parameter(torch.empty(HIDDEN, HIDDEN))
        self.gc2_b = nn.Parameter(torch.zeros(N_JOINTS, HIDDEN))
        self.fc = nn.Linear(N_JOINTS * HIDDEN * TEMPORAL_STATS, n_classes)
        nn.init.xavier_uniform_(self.gc1_w)
        nn.init.xavier_uniform_(self.gc2_w)

    def graph_layer(self, x, weight, bias):
        aggregated = torch.einsum("vw,btwc->btvc", self.graph, x)
        return torch.relu(torch.einsum("btvc,ch->btvh", aggregated, weight) + bias)

    def forward(self, x):
        x = self.graph_layer(x, self.gc1_w, self.gc1_b)
        x = self.graph_layer(x, self.gc2_w, self.gc2_b)
        mean = x.mean(dim=1)
        std = x.std(dim=1, unbiased=False)
        velocity = (x[:, 1:] - x[:, :-1]).abs().mean(dim=1)
        motion_range = x.amax(dim=1) - x.amin(dim=1)
        features = torch.cat((mean, std, velocity, motion_range), dim=1)
        return self.fc(features.flatten(1))


def subject_split(subjects: np.ndarray, seed: int):
    unique = sorted(set(subjects.tolist()))
    if len(unique) < 3:
        raise ValueError("Need at least three distinct subjects/sessions for train/val/test")
    rng = random.Random(seed)
    rng.shuffle(unique)
    n_test = max(1, round(len(unique) * 0.2))
    n_val = max(1, round(len(unique) * 0.2))
    test = set(unique[:n_test])
    val = set(unique[n_test:n_test + n_val])
    train = set(unique[n_test + n_val:])
    if not train:
        raise ValueError("Subject split left no training subjects")
    return train, val, test


def requested_subject_split(subjects: np.ndarray, train, validation, test):
    requested = [set(train), set(validation), set(test)]
    if not any(requested):
        return None
    if not all(requested):
        raise ValueError(
            "Explicit split requires --train-subjects, --validation-subjects, and --test-subjects"
        )
    if (requested[0] & requested[1]) or (requested[0] & requested[2]) or (requested[1] & requested[2]):
        raise ValueError("Explicit subject splits must be disjoint")
    available = set(subjects.tolist())
    missing = set.union(*requested) - available
    if missing:
        raise ValueError(f"Explicit split references missing subjects: {sorted(missing)}")
    return tuple(requested)


def indices_for(subjects, selected):
    return np.asarray([i for i, subject in enumerate(subjects) if subject in selected])


def evaluate(model, loader, device, n_classes):
    model.eval()
    total_loss = 0.0
    total = 0
    correct = 0
    confusion = np.zeros((n_classes, n_classes), dtype=np.int64)
    loss_fn = nn.CrossEntropyLoss()
    with torch.no_grad():
        for x, y in loader:
            x, y = x.to(device), y.to(device)
            logits = model(x)
            loss = loss_fn(logits, y)
            predictions = logits.argmax(dim=1)
            total_loss += float(loss.detach()) * len(y)
            total += len(y)
            correct += int((predictions == y).sum())
            for truth, prediction in zip(y.cpu().numpy(), predictions.cpu().numpy()):
                confusion[truth, prediction] += 1
    return total_loss / max(total, 1), correct / max(total, 1), confusion


def classification_metrics(confusion: np.ndarray, labels: list[str]) -> dict:
    per_class = {}
    recalls = []
    for index, label in enumerate(labels):
        true_positive = int(confusion[index, index])
        support = int(confusion[index].sum())
        predicted = int(confusion[:, index].sum())
        precision = true_positive / predicted if predicted else 0.0
        recall = true_positive / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        if support:
            recalls.append(recall)
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
        }

    result = {
        "balanced_accuracy": float(np.mean(recalls)) if recalls else 0.0,
        "per_class": per_class,
    }
    if "unknown" in labels:
        unknown_index = labels.index("unknown")
        unknown_total = int(confusion[unknown_index].sum())
        false_accepts = int(confusion[unknown_index].sum() - confusion[unknown_index, unknown_index])
        result["unknown_false_accept_rate"] = (
            false_accepts / unknown_total if unknown_total else None
        )
    return result


def class_counts(y: np.ndarray, indices: np.ndarray, labels: list[str]) -> dict[str, int]:
    counts = np.bincount(y[indices], minlength=len(labels))
    return {label: int(counts[index]) for index, label in enumerate(labels)}


def class_weights(y: np.ndarray, indices: np.ndarray, n_classes: int, mode: str) -> np.ndarray:
    counts = np.bincount(y[indices], minlength=n_classes).astype(np.float64)
    if np.any(counts == 0):
        missing = np.flatnonzero(counts == 0).tolist()
        raise ValueError(f"Training split has no samples for class indices: {missing}")
    if mode == "none":
        weights = np.ones(n_classes, dtype=np.float64)
    elif mode == "inverse":
        weights = 1.0 / counts
    else:
        weights = 1.0 / np.sqrt(counts)
    weights /= weights.mean()
    return weights.astype(np.float32)


def plot_history(history, confusion, labels, output_dir):
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    axes[0].plot(history["train_loss"], label="train")
    axes[0].plot(history["val_loss"], label="validation")
    axes[0].set_title("Loss")
    axes[0].set_xlabel("Epoch")
    axes[0].legend()
    axes[1].plot(history["train_accuracy"], label="train")
    axes[1].plot(history["val_accuracy"], label="validation")
    if "val_balanced_accuracy" in history:
        axes[1].plot(
            history["val_balanced_accuracy"],
            label="validation balanced",
            linestyle="--",
        )
    axes[1].set_title("Accuracy")
    axes[1].set_xlabel("Epoch")
    axes[1].set_ylim(0, 1)
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(output_dir / "training_curves.png", dpi=160)
    plt.close(fig)

    plot_confusion(confusion, labels, output_dir)


def plot_confusion(confusion, labels, output_dir):

    fig, ax = plt.subplots(figsize=(7, 6))
    image = ax.imshow(confusion, cmap="Blues")
    ax.set_xticks(range(len(labels)), labels, rotation=45, ha="right")
    ax.set_yticks(range(len(labels)), labels)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Ground truth")
    for row in range(len(labels)):
        for col in range(len(labels)):
            ax.text(col, row, str(confusion[row, col]), ha="center", va="center")
    fig.colorbar(image, ax=ax)
    fig.tight_layout()
    fig.savefig(output_dir / "confusion_matrix.png", dpi=160)
    plt.close(fig)

    row_totals = confusion.sum(axis=1, keepdims=True)
    normalized = np.divide(
        confusion,
        row_totals,
        out=np.zeros_like(confusion, dtype=np.float64),
        where=row_totals != 0,
    )
    fig, ax = plt.subplots(figsize=(7, 6))
    image = ax.imshow(normalized, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(labels)), labels, rotation=45, ha="right")
    ax.set_yticks(range(len(labels)), labels)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Ground truth")
    ax.set_title("Row-normalized confusion matrix")
    for row in range(len(labels)):
        for col in range(len(labels)):
            ax.text(col, row, f"{normalized[row, col]:.0%}", ha="center", va="center")
    fig.colorbar(image, ax=ax)
    fig.tight_layout()
    fig.savefig(output_dir / "confusion_matrix_normalized.png", dpi=160)
    plt.close(fig)


def export_weights(model, graph, labels, mean, std, output_dir, coordinate_mode, target_fps):
    state = model.cpu()
    payload = {
        "gc1_W": state.gc1_w.detach().numpy().tolist(),
        "gc1_b": state.gc1_b.detach().numpy().tolist(),
        "gc2_W": state.gc2_w.detach().numpy().tolist(),
        "gc2_b": state.gc2_b.detach().numpy().tolist(),
        "fc_W": state.fc.weight.detach().numpy().T.tolist(),
        "fc_b": state.fc.bias.detach().numpy().tolist(),
        "adjacency": graph.tolist(),
        "labels": labels,
        "temporal_pooling": TEMPORAL_POOLING,
        "input_coordinate_mode": coordinate_mode,
        "normalization_mode": f"torso_{coordinate_mode}",
        "target_fps": target_fps,
    }
    (output_dir / "stgcn_weights.json").write_text(json.dumps(payload), encoding="utf-8")
    (output_dir / "stgcn_scaler.json").write_text(
        json.dumps({"mean": mean.reshape(-1).tolist(), "std": std.reshape(-1).tolist()}),
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument(
        "--coordinate-mode",
        default="xy",
        choices=["xy", "xyz"],
        help="Use xy for compatibility with MM-Fit's public 2D pose source.",
    )
    parser.add_argument("--target-fps", type=float, default=15.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-subjects", nargs="*", default=[])
    parser.add_argument("--validation-subjects", nargs="*", default=[])
    parser.add_argument("--test-subjects", nargs="*", default=[])
    parser.add_argument(
        "--init-checkpoint",
        type=Path,
        help="Optional same-label checkpoint used to initialize domain adaptation.",
    )
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda", "xpu"])
    parser.add_argument("--dataloader-workers", type=int, default=0)
    parser.add_argument("--cpu-threads", type=int, default=0)
    parser.add_argument(
        "--patience",
        type=int,
        default=6,
        help="Stop after this many epochs without validation-accuracy improvement; 0 disables early stopping.",
    )
    parser.add_argument(
        "--class-balance", default="sqrt", choices=["none", "sqrt", "inverse"]
    )
    parser.add_argument(
        "--selection-metric",
        default="balanced_accuracy",
        choices=["accuracy", "balanced_accuracy"],
        help="Metric used for best-checkpoint selection and early stopping.",
    )
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    data = load_dataset(args.dataset, mmap_mode="r")
    x = data["x"]
    y = np.asarray(data["y"], dtype=np.int64)
    subjects = data["subjects"].astype(str)
    labels = data["labels"].astype(str).tolist()
    if x.ndim != 4 or x.shape[2:] != (N_JOINTS, COORD_DIM):
        raise ValueError(f"Expected x shape [N,T,17,3], got {x.shape}")

    explicit_split = requested_subject_split(
        subjects,
        args.train_subjects,
        args.validation_subjects,
        args.test_subjects,
    )
    train_subjects, val_subjects, test_subjects = (
        explicit_split if explicit_split is not None else subject_split(subjects, args.seed)
    )
    train_idx = indices_for(subjects, train_subjects)
    val_idx = indices_for(subjects, val_subjects)
    test_idx = indices_for(subjects, test_subjects)
    mean, std = streaming_mean_std(x, train_idx, args.coordinate_mode)
    weights = class_weights(y, train_idx, len(labels), args.class_balance)

    def loader(indices, shuffle):
        dataset = WindowDataset(x, y, indices, mean, std, args.coordinate_mode)
        return DataLoader(
            dataset,
            batch_size=args.batch_size,
            shuffle=shuffle,
            num_workers=args.dataloader_workers,
            persistent_workers=args.dataloader_workers > 0,
        )

    train_loader = loader(train_idx, True)
    val_loader = loader(val_idx, False)
    test_loader = loader(test_idx, False)
    device = choose_device(args.device)
    cpu_threads = args.cpu_threads or min(8, max(1, (torch.get_num_threads() + 1) // 2))
    if device.type == "cpu":
        torch.set_num_threads(cpu_threads)
    print(
        f"device={device.type} batch_size={args.batch_size} "
        f"dataloader_workers={args.dataloader_workers} cpu_threads={torch.get_num_threads()}"
    )
    graph = adjacency()
    model = BrowserSTGCN(len(labels), graph).to(device)
    if args.init_checkpoint:
        initial = torch.load(args.init_checkpoint, map_location="cpu", weights_only=False)
        initial_labels = [str(label) for label in initial["labels"]]
        if initial_labels != labels:
            raise ValueError(
                "Initialization checkpoint label order differs from the dataset: "
                f"checkpoint={initial_labels}, dataset={labels}"
            )
        model.load_state_dict(initial["state_dict"])
    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate)
    loss_fn = nn.CrossEntropyLoss(weight=torch.tensor(weights, device=device))
    history = {
        "train_loss": [],
        "val_loss": [],
        "train_accuracy": [],
        "val_accuracy": [],
        "val_balanced_accuracy": [],
        "val_unknown_false_accept_rate": [],
    }
    best_state = None
    best_selection_value = -1.0
    best_val_accuracy = -1.0
    best_val_balanced_accuracy = -1.0
    best_epoch = 0
    epochs_without_improvement = 0

    for epoch in range(args.epochs):
        model.train()
        total_loss = total = correct = 0
        for batch_x, batch_y in train_loader:
            batch_x, batch_y = batch_x.to(device), batch_y.to(device)
            optimizer.zero_grad()
            logits = model(batch_x)
            loss = loss_fn(logits, batch_y)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.detach()) * len(batch_y)
            total += len(batch_y)
            correct += int((logits.argmax(1) == batch_y).sum())
        val_loss, val_accuracy, val_confusion = evaluate(
            model, val_loader, device, len(labels)
        )
        val_metrics = classification_metrics(val_confusion, labels)
        val_balanced_accuracy = float(val_metrics["balanced_accuracy"])
        val_unknown_far = val_metrics.get("unknown_false_accept_rate")
        selection_value = (
            val_accuracy
            if args.selection_metric == "accuracy"
            else val_balanced_accuracy
        )
        history["train_loss"].append(total_loss / max(total, 1))
        history["train_accuracy"].append(correct / max(total, 1))
        history["val_loss"].append(val_loss)
        history["val_accuracy"].append(val_accuracy)
        history["val_balanced_accuracy"].append(val_balanced_accuracy)
        history["val_unknown_false_accept_rate"].append(val_unknown_far)
        if selection_value > best_selection_value:
            best_selection_value = selection_value
            best_val_accuracy = val_accuracy
            best_val_balanced_accuracy = val_balanced_accuracy
            best_epoch = epoch + 1
            epochs_without_improvement = 0
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
        else:
            epochs_without_improvement += 1
        print(
            f"epoch={epoch + 1:03d} train_acc={history['train_accuracy'][-1]:.3f} "
            f"val_acc={val_accuracy:.3f} val_bal={val_balanced_accuracy:.3f}"
        )
        if args.patience > 0 and epochs_without_improvement >= args.patience:
            print(
                f"early_stop epoch={epoch + 1:03d} "
                f"best_epoch={best_epoch:03d} "
                f"best_{args.selection_metric}={best_selection_value:.3f}"
            )
            break

    model.load_state_dict(best_state)
    test_loss, test_accuracy, confusion = evaluate(model, test_loader, device, len(labels))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "labels": labels,
        "device": device.type,
        "memory_mapped_dataset": args.dataset.is_dir(),
        "class_balance": args.class_balance,
        "coordinate_mode": args.coordinate_mode,
        "target_fps": args.target_fps,
        "initial_checkpoint": str(args.init_checkpoint.resolve()) if args.init_checkpoint else None,
        "class_weights": {
            label: float(weights[index]) for index, label in enumerate(labels)
        },
        "train_subjects": sorted(train_subjects),
        "validation_subjects": sorted(val_subjects),
        "test_subjects": sorted(test_subjects),
        "history": history,
        "selection_metric": args.selection_metric,
        "best_selection_value": best_selection_value,
        "best_validation_accuracy": best_val_accuracy,
        "best_validation_balanced_accuracy": best_val_balanced_accuracy,
        "best_epoch": best_epoch,
        "stopped_epoch": len(history["val_accuracy"]),
        "early_stopping_patience": args.patience,
        "test_loss": test_loss,
        "test_accuracy": test_accuracy,
        "test_metrics": classification_metrics(confusion, labels),
        "class_counts": {
            "train": class_counts(y, train_idx, labels),
            "validation": class_counts(y, val_idx, labels),
            "test": class_counts(y, test_idx, labels),
        },
        "confusion_matrix": confusion.tolist(),
    }
    (args.output_dir / "training_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    checkpoint = {
        "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()},
        "labels": labels,
        "mean": mean,
        "std": std,
        "graph": graph,
        "temporal_pooling": TEMPORAL_POOLING,
        "coordinate_mode": args.coordinate_mode,
        "target_fps": args.target_fps,
    }
    torch.save(checkpoint, args.output_dir / "stgcn_checkpoint.pt")
    export_weights(
        model,
        graph,
        labels,
        mean,
        std,
        args.output_dir,
        args.coordinate_mode,
        args.target_fps,
    )
    plot_history(history, confusion, labels, args.output_dir)
    print(f"test_accuracy={test_accuracy:.3f}")
    print(f"artifacts saved to {args.output_dir}")


if __name__ == "__main__":
    main()

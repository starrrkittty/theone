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
from torch.utils.data import DataLoader, TensorDataset


HIDDEN = 64
N_JOINTS = 17
COORD_DIM = 3


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
        self.fc = nn.Linear(N_JOINTS * HIDDEN, n_classes)
        nn.init.xavier_uniform_(self.gc1_w)
        nn.init.xavier_uniform_(self.gc2_w)

    def graph_layer(self, x, weight, bias):
        aggregated = torch.einsum("vw,btwc->btvc", self.graph, x)
        return torch.relu(torch.einsum("btvc,ch->btvh", aggregated, weight) + bias)

    def forward(self, x):
        x = self.graph_layer(x, self.gc1_w, self.gc1_b)
        x = self.graph_layer(x, self.gc2_w, self.gc2_b)
        return self.fc(x.mean(dim=1).flatten(1))


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
            total_loss += float(loss) * len(y)
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


def plot_history(history, confusion, labels, output_dir):
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    axes[0].plot(history["train_loss"], label="train")
    axes[0].plot(history["val_loss"], label="validation")
    axes[0].set_title("Loss")
    axes[0].set_xlabel("Epoch")
    axes[0].legend()
    axes[1].plot(history["train_accuracy"], label="train")
    axes[1].plot(history["val_accuracy"], label="validation")
    axes[1].set_title("Accuracy")
    axes[1].set_xlabel("Epoch")
    axes[1].set_ylim(0, 1)
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(output_dir / "training_curves.png", dpi=160)
    plt.close(fig)

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


def export_weights(model, graph, labels, mean, std, output_dir):
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
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    data = np.load(args.dataset, allow_pickle=False)
    x = data["x"].astype(np.float32)
    y = data["y"].astype(np.int64)
    subjects = data["subjects"].astype(str)
    labels = data["labels"].astype(str).tolist()
    if x.ndim != 4 or x.shape[2:] != (N_JOINTS, COORD_DIM):
        raise ValueError(f"Expected x shape [N,T,17,3], got {x.shape}")

    train_subjects, val_subjects, test_subjects = subject_split(subjects, args.seed)
    train_idx = indices_for(subjects, train_subjects)
    val_idx = indices_for(subjects, val_subjects)
    test_idx = indices_for(subjects, test_subjects)
    mean = x[train_idx].mean(axis=(0, 1))
    std = x[train_idx].std(axis=(0, 1))
    std = np.where(std < 1e-6, 1.0, std)
    x = (x - mean[None, None]) / std[None, None]

    def loader(indices, shuffle):
        dataset = TensorDataset(torch.from_numpy(x[indices]), torch.from_numpy(y[indices]))
        return DataLoader(dataset, batch_size=args.batch_size, shuffle=shuffle)

    train_loader = loader(train_idx, True)
    val_loader = loader(val_idx, False)
    test_loader = loader(test_idx, False)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    graph = adjacency()
    model = BrowserSTGCN(len(labels), graph).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate)
    loss_fn = nn.CrossEntropyLoss()
    history = {"train_loss": [], "val_loss": [], "train_accuracy": [], "val_accuracy": []}
    best_state = None
    best_val = -1.0

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
            total_loss += float(loss) * len(batch_y)
            total += len(batch_y)
            correct += int((logits.argmax(1) == batch_y).sum())
        val_loss, val_accuracy, _ = evaluate(model, val_loader, device, len(labels))
        history["train_loss"].append(total_loss / max(total, 1))
        history["train_accuracy"].append(correct / max(total, 1))
        history["val_loss"].append(val_loss)
        history["val_accuracy"].append(val_accuracy)
        if val_accuracy > best_val:
            best_val = val_accuracy
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
        print(f"epoch={epoch + 1:03d} train_acc={history['train_accuracy'][-1]:.3f} val_acc={val_accuracy:.3f}")

    model.load_state_dict(best_state)
    test_loss, test_accuracy, confusion = evaluate(model, test_loader, device, len(labels))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "labels": labels,
        "train_subjects": sorted(train_subjects),
        "validation_subjects": sorted(val_subjects),
        "test_subjects": sorted(test_subjects),
        "history": history,
        "best_validation_accuracy": best_val,
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
    export_weights(model, graph, labels, mean, std, args.output_dir)
    plot_history(history, confusion, labels, args.output_dir)
    print(f"test_accuracy={test_accuracy:.3f}")
    print(f"artifacts saved to {args.output_dir}")


if __name__ == "__main__":
    main()

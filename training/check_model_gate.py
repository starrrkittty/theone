"""Fail closed when an evaluation report is not safe to promote to the App."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--min-accuracy", type=float, default=0.80)
    parser.add_argument("--min-balanced-accuracy", type=float, default=0.75)
    parser.add_argument("--min-class-recall", type=float, default=0.55)
    parser.add_argument("--max-unknown-false-accept", type=float, default=0.10)
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    metrics = report.get("metrics", report.get("test_metrics", {}))
    accuracy = float(report.get("accuracy", report.get("test_accuracy", 0.0)))
    balanced = float(metrics.get("balanced_accuracy", 0.0))
    unknown_far = metrics.get("unknown_false_accept_rate")
    failures: list[str] = []
    if accuracy < args.min_accuracy:
        failures.append(f"accuracy {accuracy:.3f} < {args.min_accuracy:.3f}")
    if balanced < args.min_balanced_accuracy:
        failures.append(
            f"balanced_accuracy {balanced:.3f} < {args.min_balanced_accuracy:.3f}"
        )
    if unknown_far is None or float(unknown_far) > args.max_unknown_false_accept:
        failures.append(
            f"unknown_false_accept_rate {unknown_far} > {args.max_unknown_false_accept:.3f}"
        )
    for label, values in metrics.get("per_class", {}).items():
        if int(values.get("support", 0)) == 0:
            continue
        recall = float(values.get("recall", 0.0))
        if recall < args.min_class_recall:
            failures.append(
                f"{label} recall {recall:.3f} < {args.min_class_recall:.3f}"
            )

    result = {
        "passed": not failures,
        "report": str(args.report.resolve()),
        "failures": failures,
    }
    print(json.dumps(result, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

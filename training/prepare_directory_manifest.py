"""Create a leakage-aware training manifest from class-organized videos.

Expected layouts are either ``<class>/<subject>/<video>`` or
``<class>/<video>``.  The latter treats each source clip as an independent
subject/session, which is suitable only when every clip comes from a distinct
source recording (for example, curated HAA500 clips).
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
SUPPORTED_LABELS = {
    "squat", "pushup", "plank", "bicep_curl", "alternate_bicep_curl",
    "lunge", "situp", "tricep_extension", "dumbbell_row",
    "jumping_jack", "shoulder_press", "lateral_raise", "unknown",
}


def load_label_map(path: Path) -> dict[str, str | None]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Label map must be a JSON object")
    result: dict[str, str | None] = {}
    for raw_label, target_label in payload.items():
        raw = str(raw_label).strip()
        if not raw:
            raise ValueError("Label map contains an empty source label")
        if target_label is None:
            result[raw] = None
            continue
        target = str(target_label).strip()
        if target not in SUPPORTED_LABELS:
            raise ValueError(f"Unsupported target label for {raw!r}: {target!r}")
        result[raw] = target
    return result


def infer_subject(
    relative_path: Path,
    mode: str,
    subject_pattern: re.Pattern[str] | None,
) -> str:
    if mode == "file":
        return relative_path.stem
    if mode == "parent":
        # <class>/<subject>/<video>; fall back to the clip id when no subject
        # directory is present rather than collapsing a whole class to one id.
        return relative_path.parts[1] if len(relative_path.parts) >= 3 else relative_path.stem
    if subject_pattern is None:
        raise ValueError("subject_pattern is required for regex mode")
    match = subject_pattern.search(relative_path.as_posix())
    if not match:
        raise ValueError(f"Subject regex did not match {relative_path.as_posix()!r}")
    if "subject" in match.groupdict():
        subject = match.group("subject")
    elif match.lastindex:
        subject = match.group(1)
    else:
        subject = match.group(0)
    if not subject:
        raise ValueError(f"Subject regex produced an empty id for {relative_path.as_posix()!r}")
    return subject


def build_manifest(
    dataset_root: Path,
    label_map: dict[str, str | None],
    subject_mode: str = "parent",
    subject_regex: str | None = None,
    extensions: set[str] | None = None,
) -> tuple[list[dict], dict]:
    root = dataset_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Dataset root does not exist: {root}")
    suffixes = {value.lower() for value in (extensions or VIDEO_EXTENSIONS)}
    pattern = re.compile(subject_regex) if subject_regex else None
    if subject_mode == "regex" and pattern is None:
        raise ValueError("--subject-regex is required when --subject-mode=regex")

    entries: list[dict] = []
    ignored = Counter()
    source_counts = Counter()
    for video_path in sorted(root.rglob("*")):
        if not video_path.is_file() or video_path.suffix.lower() not in suffixes:
            continue
        relative = video_path.relative_to(root)
        if len(relative.parts) < 2:
            ignored["video_not_below_class_directory"] += 1
            continue
        source_label = relative.parts[0]
        if source_label not in label_map:
            ignored[f"unmapped:{source_label}"] += 1
            continue
        target_label = label_map[source_label]
        if target_label is None:
            ignored[f"explicitly_ignored:{source_label}"] += 1
            continue
        subject = infer_subject(relative, subject_mode, pattern)
        entries.append({
            "path": relative.as_posix(),
            "label": target_label,
            "subject": subject,
            "source_label": source_label,
        })
        source_counts[source_label] += 1

    if not entries:
        raise ValueError("No mapped video files were found")
    subject_sets: dict[str, set[str]] = defaultdict(set)
    label_counts = Counter()
    for entry in entries:
        label_counts[entry["label"]] += 1
        subject_sets[entry["label"]].add(entry["subject"])
    audit = {
        "videos": len(entries),
        "label_counts": dict(sorted(label_counts.items())),
        "subjects_per_label": {
            label: len(subjects) for label, subjects in sorted(subject_sets.items())
        },
        "source_label_counts": dict(sorted(source_counts.items())),
        "ignored": dict(sorted(ignored.items())),
    }
    return entries, audit


def validate_subject_coverage(entries: list[dict], minimum: int) -> None:
    subjects: dict[str, set[str]] = defaultdict(set)
    for entry in entries:
        subjects[entry["label"]].add(entry["subject"])
    sparse = {label: len(ids) for label, ids in subjects.items() if len(ids) < minimum}
    if sparse:
        raise ValueError(
            f"Need at least {minimum} independent subjects/sessions per label; got {sparse}. "
            "Do not split adjacent clips from one recording across train/test."
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--label-map", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--license", required=True)
    parser.add_argument("--license-url")
    parser.add_argument(
        "--subject-mode", choices=("parent", "file", "regex"), default="parent",
        help="parent=<class>/<subject>/<video>; file=one independent source clip per file",
    )
    parser.add_argument("--subject-regex")
    parser.add_argument("--min-subjects-per-label", type=int, default=3)
    args = parser.parse_args()

    label_map = load_label_map(args.label_map.resolve())
    entries, audit = build_manifest(
        args.dataset_root, label_map, args.subject_mode, args.subject_regex
    )
    validate_subject_coverage(entries, args.min_subjects_per_label)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    # build_windows.py resolves relative paths from the manifest directory, not
    # from dataset_root.  Rebase here so a manifest can live beside, rather than
    # inside, a read-only public dataset extraction.
    for entry in entries:
        video_path = args.dataset_root.resolve() / entry["path"]
        entry["path"] = Path(os.path.relpath(video_path, args.output.parent.resolve())).as_posix()
    args.output.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    provenance_path = args.output.with_suffix(".provenance.json")
    provenance = {
        "dataset_id": args.dataset_id,
        "source_url": args.source_url,
        "license": args.license,
        "license_url": args.license_url,
        "dataset_root": str(args.dataset_root.resolve()),
        "manifest": str(args.output.resolve()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "subject_mode": args.subject_mode,
        "subject_regex": args.subject_regex,
        "label_map": label_map,
        "audit": audit,
        "warning": (
            "Public labels describe action identity, not form quality. "
            "Keep source recordings separated across train/validation/test."
        ),
    }
    provenance_path.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"saved {len(entries)} videos to {args.output}")
    print(f"labels: {audit['label_counts']}")
    print(f"subjects per label: {audit['subjects_per_label']}")
    print(f"provenance: {provenance_path}")


if __name__ == "__main__":
    main()

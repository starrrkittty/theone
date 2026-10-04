import json
import re
from pathlib import Path
from functools import lru_cache
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=32)
def _file_content(path, modified_ns, size):
    return Path(path).read_text(encoding="utf-8")


def read_cached(path):
    stat = path.stat()
    return _file_content(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=8)
def _json_content(text):
    return json.loads(text)


def load_skill(name):
    folder = ROOT / "skills" / name
    text = read_cached(folder / "SKILL.md")
    for path in sorted((folder / "references").glob("*.md")):
        text += "\n\n" + read_cached(path)
    return text


def retrieve_knowledge(task, specialist, query, exercise_id=None):
    entries = _json_content(read_cached(ROOT / "knowledge" / "entries.json"))
    sources = {item["id"]: item for item in _json_content(read_cached(ROOT / "knowledge" / "sources.json"))}
    manifest_path = ROOT / "knowledge" / "fetch_manifest.json"
    if manifest_path.exists():
        for record in _json_content(read_cached(manifest_path)):
            if record["id"] in sources:
                sources[record["id"]] = {**sources[record["id"]], "fetch_provenance": record}
    tokens = set(re.findall(r"\w+", query.lower()))
    selected = []
    for entry in entries:
        if task == "movement" and entry.get("exercise_ids") and exercise_id not in entry["exercise_ids"]:
            continue
        tags = set(entry["tags"])
        if task == "movement" and entry.get("specialist_only") and specialist not in tags:
            continue
        score = 5 * (task in tags) + 8 * (specialist in tags) + len(tokens & set(re.findall(r"\w+", entry["text"].lower())))
        if task not in tags and specialist not in tags:
            continue
        selected.append((score, {**entry, "source": sources[entry["source_id"]]}))
    return deepcopy([item for _, item in sorted(selected, key=lambda item: item[0], reverse=True)[:5]])

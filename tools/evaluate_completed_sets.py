"""Development diagnostic for retrospective set decisions; no model requests."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/".deps"), str(ROOT/"backend"), str(ROOT/"coach")]
from perception.sets import analyze_set


def evaluate(document):
    rows = []
    for clip in document["sequences"]:
        frames = [{**frame, "timestamp":1700000000000+frame["timestamp_ms"]} for frame in clip["frames"]]
        started = time.perf_counter()
        result, _ = analyze_set(frames, clip["id"])
        predicted = sorted({segment["exercise"] for segment in result["segments"]})
        count = {label:sum(s["repetitions"] for s in result["segments"] if s["exercise"] == label) for label in predicted}
        expected = clip["expected_exercise"]
        correct = not predicted if expected == "unknown" else predicted == [expected]
        rows.append({"id":clip["id"], "original_label":clip.get("original_label"), "expected":expected,
                     "predicted":predicted or ["unknown"], "correct":correct, "repetitions":count,
                     "reference_repetitions":clip.get("reference_repetitions"),
                     "hold_seconds":max((s.get("hold_seconds",0) for s in result["segments"]),default=0),
                     "reference_hold_seconds":clip.get("reference_hold_seconds"),
                     "online_confirmed_frames":result["online_confirmed_frames"],
                     "retrospectively_resolved_frames":result["resolved_segment_frames"],
                     "analysis_ms":(time.perf_counter()-started)*1000})
    return {"evaluation_mode":"completed_set_development_diagnostic", "dataset":document.get("dataset"),
            "evidence_type":document.get("evidence_type", "unverified"),
            "model_called":False, "clips":len(rows), "correct_clip_decisions":sum(row["correct"] for row in rows),
            "limitations":document.get("limitations", [])+[
                "Development diagnostic; not held-out real-video validation.",
                "Retrospective segment labels are not real-time frame recall.",
                "Clip decisions cannot establish real-video generalization accuracy."], "results":rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(json.loads(args.input.read_text(encoding="utf-8-sig")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))

"""Replay labelled keypoints against A with a virtual clock; never calls an LLM."""
import argparse
from collections import Counter
import json
import math
import inspect
import time
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LABELS = ("unknown","squat","pushup","plank","bicep_curl","alternate_bicep_curl")


def evaluate(document, manager_class, builder_class, perception_class=None):
    confusion = Counter()
    sequences = []
    processing_ms, evidence_chars, full_report_chars = [], [], []
    handoffs, valid_b_inputs = 0, 0
    supports_aspect = "image_aspect_ratio" in inspect.signature(manager_class.process_frame).parameters
    for sequence in document["sequences"]:
        manager = manager_class()
        builder = builder_class(sequence["id"])
        perception = perception_class() if perception_class else None
        clock = [1700000000.0]
        first_confirmed = None
        start_ms = None
        previous_ms = None
        switches = 0
        rep_counts = {}
        rows = []
        for frame in sequence["frames"]:
            expected = frame.get("expected_exercise", sequence.get("expected_exercise"))
            if expected not in LABELS:
                raise ValueError("Every evaluated frame needs a supported expected_exercise")
            stamp = frame["timestamp_ms"]
            if type(stamp) not in {int,float} or not math.isfinite(stamp) or (previous_ms is not None and stamp <= previous_ms):
                raise ValueError("Frame timestamps must be finite and strictly increasing")
            previous_ms = stamp
            start_ms = stamp if start_ms is None else start_ms
            clock[0] = 1700000000 + (stamp - start_ms)/1000
            with patch("time.time", lambda:clock[0]), patch("time.monotonic", lambda:clock[0]):
                if perception:
                    from perception.pipeline import process_pose_frame
                    from perception.evidence import compact, evidence_packet
                    from app.action_report_adapter import normalize
                    from app.engine import validate_movement
                    payload = {**frame, "timestamp":clock[0]*1000}
                    state, report, event, gate, timings = process_pose_frame(manager, builder, perception, payload)
                    processing_ms.append(timings["total_ms"])
                    full_report_chars.append(len(compact(report.model_dump())))
                    evidence_chars.append(len(compact(evidence_packet(perception.latest, gate))))
                    if gate["handoff_allowed"]:
                        handoffs += 1
                        validate_movement(normalize(report.model_dump()))
                        valid_b_inputs += 1
                else:
                    options = {"image_aspect_ratio":frame.get("image_aspect_ratio",1.0)} if supports_aspect else {}
                    started = time.perf_counter()
                    state = manager.process_frame(frame["landmarks"], frame.get("client_probs"), **options)
                    report, event = builder.build(state, clock[0]*1000)
                    processing_ms.append((time.perf_counter()-started)*1000)
            predicted = report.recognized_exercise if report.recognition_status == "confirmed" else "unknown"
            confusion[(expected,predicted)] += 1
            if predicted != "unknown":
                first_confirmed = stamp-start_ms if first_confirmed is None else first_confirmed
                rep_counts[predicted] = max(rep_counts.get(predicted,0),report.repetition)
            switches += int(event is not None and event.event == "exercise_switched")
            rows.append({"timestamp_ms":stamp,"expected":expected,"predicted":predicted,
                         "status":report.recognition_status,"recognition_score":report.recognition_confidence,
                         "repetition":report.repetition,"source":state.exercise_source})
        predicted_counts = Counter(row["predicted"] for row in rows)
        majority = predicted_counts.most_common(1)[0][0] if rows else "unknown"
        reference = sequence.get("reference_repetitions")
        rep_errors = {label:abs(rep_counts.get(label,0)-value) for label,value in reference.items()} if isinstance(reference,dict) else None
        sequences.append({"id":sequence["id"],"subject_id":sequence.get("subject_id"),
                          "original_label":sequence.get("original_label"), "majority_prediction":majority,
                          "repetition_absolute_errors":rep_errors,
                          "frames":len(rows),"first_confirmed_latency_ms":first_confirmed,
                          "exercise_switches":switches,"repetition_counts":rep_counts,
                          "reference_repetitions":sequence.get("reference_repetitions"),"predictions":rows})
    total = sum(confusion.values())
    correct = sum(count for (actual,predicted),count in confusion.items() if actual==predicted)
    confirmed = sum(count for (_,predicted),count in confusion.items() if predicted!="unknown")
    confirmed_correct = sum(count for (actual,predicted),count in confusion.items() if actual==predicted and predicted!="unknown")
    metrics = {}
    for label in LABELS:
        tp = confusion[(label,label)]
        support = sum(count for (actual,_),count in confusion.items() if actual==label)
        predicted_count = sum(count for (_,predicted),count in confusion.items() if predicted==label)
        precision = tp/predicted_count if predicted_count else None
        recall = tp/support if support else None
        metrics[label] = {"support":support,"precision":precision,"recall":recall,
                          "f1":2*tp/(support+predicted_count) if support else None}
    negatives = sum(count for (actual,_),count in confusion.items() if actual=="unknown")
    false_positives = sum(count for (actual,predicted),count in confusion.items() if actual=="unknown" and predicted!="unknown")
    ordered = sorted(processing_ms)
    timing = {key:ordered[min(len(ordered)-1,int((len(ordered)-1)*percentile))] if ordered else None
              for key,percentile in (("p50_ms",.5),("p95_ms",.95),("p99_ms",.99))}
    return {"evidence_type":document.get("evidence_type","unverified"),
            "dataset":document.get("dataset"), "limitations":document.get("limitations", []),
            "label_granularity":document.get("label_granularity"),
            "pipeline_mode":"full_measured_chain" if perception_class else "recognition_only",
            "processing_latency":timing, "model_called":False,
            "handoff_frames":handoffs, "validated_b_inputs":valid_b_inputs,
            "prompt_evidence":{"mean_full_report_chars":sum(full_report_chars)/len(full_report_chars) if full_report_chars else None,
                               "mean_compact_evidence_chars":sum(evidence_chars)/len(evidence_chars) if evidence_chars else None,
                               "unit":"characters, not tokens"},
            "scope":"Labelled landmark replay; does not evaluate video-to-pose quality or AI coaching quality",
            "total_frames":total,"overall_accuracy":correct/total if total else None,
            "confirmed_accuracy":confirmed_correct/confirmed if confirmed else None,
            "recognition_coverage":confirmed/total if total else None,
            "negative_false_positive_rate":false_positives/negatives if negatives else None,
            "per_class":metrics,"confusion_matrix":{label:{p:confusion[(label,p)] for p in LABELS} for label in LABELS},
            "sequences":sequences}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend-root", type=Path, default=ROOT/"backend")
    parser.add_argument("--full-chain", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT/".deps"))
    sys.path.insert(0, str(ROOT/"coach"))
    sys.path.insert(0, str(args.backend_root.resolve()))
    from state_machine.manager import FormManager
    from reporting.builder import ActionReportBuilder
    if args.full_chain:
        from perception.agent import PerceptionSession
    result = evaluate(json.loads(args.input.read_text(encoding="utf-8-sig")),FormManager,ActionReportBuilder,
                      PerceptionSession if args.full_chain else None)
    result["backend_root"] = str(args.backend_root.resolve())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({key:result[key] for key in ("evidence_type","total_frames","overall_accuracy","negative_false_positive_rate")},ensure_ascii=False))

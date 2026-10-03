"""Bounded capture and two-pass completed-set analysis. No model calls here."""
from collections import Counter
from copy import deepcopy
import math
import time
from uuid import uuid4

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator

from pipeline.clock import observation_time
from pipeline.confidence import ConfidenceComposer
from pipeline.features import FeatureExtractor
from pipeline.validator import QualityFlags
from reporting.builder import ActionReportBuilder
from state_machine.manager import FormManager, FormManagerState, SystemState, _EXERCISE_MODULES
from exercises.base import ExerciseType
from perception.agent import PerceptionSession
from perception.quality import sequence_quality
from pipeline.form_evaluator import FormEvaluator

MAX_SET_FRAMES = 2400


class Point(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
    x: float = Field(ge=-10, le=10)
    y: float = Field(ge=-10, le=10)
    z: float = Field(default=0, ge=-10, le=10)
    visibility: float = Field(default=0, ge=0, le=1)


class BufferedFrame(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
    timestamp: float = Field(gt=0)
    landmarks: list[Point] = Field(max_length=33)
    world_landmarks: list[Point] | None = Field(default=None, max_length=33)
    image_aspect_ratio: float = Field(default=1, ge=.1, le=20)
    client_probs: dict[str, float] | None = Field(default=None, max_length=64)
    camera_view: str = Field(default="auto", max_length=20)
    capture_profile: str = Field(default="unspecified", pattern="^(unspecified|frontal_v1|exercise_view_v1)$")

    @field_validator("landmarks", "world_landmarks")
    @classmethod
    def check_count(cls, value):
        if value is not None and len(value) not in {0, 33}:
            raise ValueError("Expected zero or 33 landmarks")
        return value


def capture_frame(session, payload):
    try:
        frame = BufferedFrame.model_validate(payload)
        if len(frame.landmarks) not in {0, 33}:
            raise ValueError("Expected zero or 33 landmarks")
        if frame.client_probs and any(not math.isfinite(v) or not 0 <= v <= 1 for v in frame.client_probs.values()):
            raise ValueError("Invalid classification probabilities")
    except ValueError:
        session.buffer_rejected += 1
        return
    if len(session.frame_buffer) == MAX_SET_FRAMES:
        session.buffer_dropped += 1
    session.frame_buffer.append(frame.model_dump(exclude_none=True))


def buffer_status(session):
    return {"frames":len(session.frame_buffer), "capacity":MAX_SET_FRAMES,
            "dropped_frames":session.buffer_dropped, "rejected_frames":session.buffer_rejected}


def analyze_set(frames, session_id, dropped=0, rejected=0):
    if not frames:
        raise ValueError("No buffered frames")
    started = time.perf_counter()
    manager = FormManager()
    observations, chunks, chunk = [], [], []
    previous = None
    last_pose_stamp = None
    for payload in frames:
        stamp = payload["timestamp"]
        if previous is not None and (stamp <= previous or stamp-previous > 750):
            if chunk:
                chunks.append(chunk)
                chunk = []
            manager.reset()
        previous = stamp
        if len(payload["landmarks"]) != 33:
            if last_pose_stamp is not None and 0 <= stamp-last_pose_stamp <= 500:
                continue
            if chunk:
                chunks.append(chunk)
                chunk=[]
            manager.reset()
            continue
        if last_pose_stamp is not None and stamp-last_pose_stamp > 500:
            if chunk:
                chunks.append(chunk)
                chunk=[]
            manager.reset()
        last_pose_stamp=stamp
        with observation_time(stamp/1000):
            state = manager.process_frame(payload["landmarks"], payload.get("client_probs"), payload.get("image_aspect_ratio", 1))
        if len(payload["landmarks"]) != 33 or not manager._filtered_landmarks:
            if chunk:
                chunks.append(chunk)
                chunk = []
            manager.reset()
            continue
        points = deepcopy(manager._filtered_landmarks)
        uncertainty = np.trace(manager._kalman._P[:, :3, :3], axis1=1, axis2=2)
        array = np.asarray(points)
        body = FeatureExtractor().extract(array[:,:3], uncertainty, array[:,3])
        item = {"payload":payload, "points":points, "body":body,
                "tracking_observations":deepcopy(manager._kalman.observation_metadata),
                "confirmed":state.current_exercise.value if state.current_exercise else None,
                "candidate":state.candidate_exercise.value if state.candidate_exercise else None,
                "score":state.exercise_confidence}
        observations.append(item)
        chunk.append(item)
    if chunk:
        chunks.append(chunk)

    recognized_at = time.perf_counter()
    segments, snapshots = [], []
    for chunk in chunks:
        runs = []
        for index, item in enumerate(chunk):
            label = item["confirmed"]
            if label and (not runs or runs[-1]["label"] != label):
                start = 0 if not runs else index
                if runs:
                    # Backfill only to the first matching candidate since the
                    # preceding confirmed action; never label across tracking loss.
                    start = next((j for j in range(runs[-1]["last"]+1, index+1)
                                  if chunk[j]["candidate"] == label), index)
                runs.append({"label":label, "start":start, "last":index})
            elif label:
                runs[-1]["last"] = index
        for index, run in enumerate(runs):
            end = runs[index+1]["start"] if index+1 < len(runs) else len(chunk)
            samples = chunk[run["start"]:end]
            summary, snapshot = _analyze_segment(samples, run["label"], session_id)
            segments.append(summary)
            snapshots.append(snapshot)
    result = {"schema_version":"completed_set_v1", "set_id":uuid4().hex, "session_id":session_id,
              "feedback_scope":"completed_set", "status":"analyzed" if segments else "awaiting_evidence",
              "retained_frames":len(frames), "dropped_frames":dropped, "rejected_frames":rejected,
              "start_timestamp_ms":frames[0]["timestamp"], "end_timestamp_ms":frames[-1]["timestamp"],
              "online_confirmed_frames":sum(bool(item["confirmed"]) for item in observations),
              "resolved_segment_frames":sum(s["frames"] for s in segments), "segments":segments,
              "limitations":["Completed-set retrospective labels are not real-time frame predictions.",
                             "Only previously confirmed supported actions can seed a segment; unknown sets are not forced into a class.",
                             "Counts require observed cycles; no missing repetitions are inferred.",
                             "Joint ranges are measured proxies, not recommended posture limits."]}
    if dropped or rejected:
        result["limitations"].append("Capture is incomplete; dropped/rejected frames may lose repetitions.")
    segments_at = time.perf_counter()
    result["measurement_quality"] = sequence_quality(frames)
    finished = time.perf_counter()
    result["processing"] = {"recognition_pass_ms":(recognized_at-started)*1000,
                            "segment_kinematics_pass_ms":(segments_at-recognized_at)*1000,
                            "sequence_quality_ms":(finished-segments_at)*1000,
                            "local_total_ms":(finished-started)*1000}
    return result, snapshots


def _analyze_segment(samples, label, session_id):
    module = _EXERCISE_MODULES[ExerciseType(label)]()
    builder, perception = ActionReportBuilder(session_id), PerceptionSession()
    composer = ConfidenceComposer()
    evaluator = FormEvaluator()
    angles, violations = {}, {}
    snapshot = None
    skipped, hold_seconds = 0, 0.0
    skipped_reasons = Counter()
    counting_only_frames = 0
    confirmed_scores = [s["score"] for s in samples if s["confirmed"] == label]
    score = sum(confirmed_scores)/len(confirmed_scores)
    last_report = None
    for item in samples:
        body, payload = item["body"], item["payload"]
        quality = composer.compose(score, body, QualityFlags(), label)
        compatible = body.is_horizontal == (label in {"pushup", "plank"})
        points=[{"x":x,"y":y,"z":z,"visibility":v} for x,y,z,v in item["points"]]
        counting_supported = module.counting_ready(points)
        with observation_time(payload["timestamp"]/1000):
            if not counting_supported or not compatible:
                skipped_reasons["counting_joints_unreliable" if not counting_supported else "incompatible_body_orientation"] += 1
                module.mark_unobserved()
                skipped += 1
                continue
            if quality.signal_quality == "unreliable":
                counting_only_frames += 1
            result = module.process_frame(points)
            stable=evaluator.evaluate(body,label) if quality.signal_quality != "unreliable" else []
            result.violations=[v.message for v in stable]
            result.corrections=[v.correction for v in stable if v.correction]
            hold_seconds = max(hold_seconds, float(getattr(result, "hold_seconds", 0)))
            state = FormManagerState(system_state=SystemState.ACTIVE, current_exercise=ExerciseType(label),
                exercise_result=result, exercise_confidence=score, form_confidence=quality.form_confidence,
                signal_quality=quality.signal_quality, candidate_exercise=ExerciseType(label),
                stable_violations=stable,
                candidate_confidence=score, exercise_source="completed_set", measured_angles=body.angles,
                joint_confidences={}, filtered_landmarks=item["points"])
            for name, indices in {"left_elbow":(11,13,15), "right_elbow":(12,14,16),
                                  "left_knee":(23,25,27), "right_knee":(24,26,28),
                                  "left_shoulder":(13,11,23), "right_shoulder":(14,12,24),
                                  "left_hip":(11,23,25), "right_hip":(12,24,26)}.items():
                visibility = float(min(body.visibility[list(indices)]))
                state.joint_confidences[name] = visibility
                if visibility >= .5 and name in body.angles:
                    angles.setdefault(name, []).append(body.angles[name])
            report, _ = builder.build(state, payload["timestamp"])
            report.camera_view = body.view_estimate.value
            policy = perception.update(report, item["points"], payload.get("world_landmarks"),
                                       payload.get("capture_profile"), body.view_estimate.value, payload.get("camera_view"), item.get("tracking_observations"))
            last_report = report
            if policy["handoff_allowed"]:
                snapshot = deepcopy(perception.latest)
            for violation in report.violations:
                key = violation.type
                if key not in violations:
                    violations[key] = {**violation.model_dump(), "observed_frames":0}
                violations[key]["observed_frames"] += 1
    counting_evidence=module.counting_evidence()
    uncertain_count=sum(e.get("uncertain_cycle_count",len(e.get("uncertain_cycles",[]))) for e in counting_evidence.values())
    summary = {"exercise":label, "frames":len(samples), "skipped_frames":skipped,
               "counting_evidence":counting_evidence, "uncertain_cycles":uncertain_count,
               "start_timestamp_ms":samples[0]["payload"]["timestamp"],
               "end_timestamp_ms":samples[-1]["payload"]["timestamp"],
               "repetitions":module.rep_count, "partial_repetitions":module.partial_reps,
               "observed_closed_cycles":module.rep_count+module.partial_reps,
               "counting_observation":getattr(module,"counting_observation","exercise_module_angle_proxy"),
               "rejected_cycle_diagnostics":getattr(getattr(module,"_rep_counter",None),"rejected_cycles",[]),
               "hold_seconds":hold_seconds,
               "skipped_frame_reasons":dict(skipped_reasons),
               "counting_only_frames":counting_only_frames,
               "counter_resets_for_observation_gaps":uncertain_count,
               "short_gap_policy":"retain cycle state for at most 500 ms; long gaps abandon only the pending cycle, not completed counts; predictions cannot close cycles",
               "angle_range_source":"filtered_image_width_normalized_landmarks",
               "angle_range_definition":"included_segment_angle_degrees; uncalibrated image geometry",
               "angle_ranges_deg":{name:{"min":min(v), "max":max(v), "samples":len(v)} for name,v in angles.items()},
               "violations":list(violations.values()), "agent_eligible":snapshot is not None}
    if snapshot:
        report = snapshot["action_report"]
        report["repetition"] = summary["repetitions"]
        report["metrics"]["partial_reps"] = summary["partial_repetitions"]
        report["kinematics"]["set_summary"] = deepcopy(summary)
        report["perception_agent"]["feedback_scope"] = "completed_set"
        summary["action_report"] = deepcopy(report)
    elif last_report:
        summary["action_report"] = last_report.model_dump()
    return summary, snapshot

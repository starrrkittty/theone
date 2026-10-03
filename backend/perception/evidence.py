"""Small, action-specific evidence; no raw XML or recursive Agent transcripts."""
import json
from hashlib import sha256

JOINTS = {
    "squat": ("left_knee", "right_knee", "left_hip", "right_hip", "torso_angle"),
    "pushup": ("left_elbow", "right_elbow", "left_hip", "right_hip", "torso_angle"),
    "plank": ("left_elbow", "right_elbow", "left_hip", "right_hip", "torso_angle"),
    "bicep_curl": ("left_elbow", "right_elbow", "left_shoulder", "right_shoulder", "torso_angle"),
    "alternate_bicep_curl": ("left_elbow", "right_elbow", "left_shoulder", "right_shoulder", "torso_angle"),
}


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def evidence_packet(snapshot, gate):
    report = snapshot["action_report"]
    kin = report["kinematics"]
    names = set(JOINTS.get(report["recognized_exercise"], ()))
    joints = {name + "_joint" for name in names}
    # Origins vary each frame; the stable ID identifies topology and conventions.
    definitions = {name: {key: value for key, value in spec.items() if key in {"parent", "child", "type", "axis", "lower", "upper"}}
                   for name, spec in kin.get("structure", {}).items() if name in joints}
    structure_id = sha256(compact(definitions).encode()).hexdigest()[:16]
    motion = snapshot.get("motion", {})
    return {
        "contract": "perception-evidence/v2", "structure_id": structure_id,
        "recognition": {key: report[key] for key in ("recognition_status", "recognized_exercise", "recognition_confidence", "candidate_exercises", "phase", "repetition")},
        "measurement": {key: kin.get(key) for key in ("status", "model_kind", "coordinate_space", "coordinate_units", "metric_calibrated", "parser")},
        "joint_definitions": definitions,
        "joint_states": {name: value for name, value in kin.get("joint_states", {}).items() if name in joints},
        "segment_angles_deg": {name: value for name, value in report["metrics"]["joint_angles"].items() if name in names},
        "visibility": {name: value for name, value in report["metrics"]["joint_confidences"].items() if name in names},
        "camera_view": report["camera_view"], "pose_quality": report["pose_quality"],
        "capture_view_policy":kin.get("capture_view_policy",{}),
        "tracking_summary":kin.get("tracking_summary",{}),
        "motion": {"frames": motion.get("frames", 0), "duration_seconds": motion.get("duration_seconds", 0),
                   "joints": {name: value for name, value in motion.get("joints", {}).items() if name in joints}},
        "fit": {name: value for name, value in kin.get("fit", {}).items() if name in names},
        "fk_residuals": {name: value for name, value in kin.get("fk_endpoint_residuals", {}).items() if name.removesuffix("_tip") in names},
        "residual_units": kin.get("residual_units"),
        "image_world_disagreement_deg": {name: value for name, value in kin.get("image_world_angle_disagreement_deg", {}).items() if name in names},
        "violations": [{key: item.get(key) for key in ("type", "severity", "joints", "consecutive_frames")} for item in report.get("violations", [])],
        "gate": gate,
        **({"completed_set": {key: kin["set_summary"][key] for key in
            ("frames", "skipped_frames", "start_timestamp_ms", "end_timestamp_ms", "repetitions",
             "partial_repetitions", "angle_range_source", "angle_range_definition")
            if key in kin["set_summary"]}} if isinstance(kin.get("set_summary"), dict) else {}),
    }


def review_signature(snapshot, gate):
    packet = evidence_packet(snapshot, gate)
    # Ignore phase, repetition and instantaneous hinge angle: normal reps change
    # these continuously. Changes in observed ROM/quality still trigger review.
    signal = {key: packet[key] for key in ("structure_id", "measurement", "camera_view", "pose_quality")}
    signal["view_scope"] = {key:packet["capture_view_policy"].get(key) for key in ("profile","status","supported_observations")}
    signal["recognition"] = {key: packet["recognition"][key] for key in ("recognized_exercise", "recognition_status")}
    signal["gate"] = {key: gate[key] for key in ("handoff_allowed", "missing_joints", "motion_supported")}
    signal["visibility"] = {name: int(value >= .6) + int(value >= .8) for name, value in packet["visibility"].items()}
    signal["violations"] = sorted((str(v["type"]), str(v["severity"])) for v in packet["violations"])
    signal["range"] = {name: round(value.get("trimmed_range_rad", 0)/.2) for name, value in packet["motion"]["joints"].items()}
    signal["motion_bounds"] = {name: [round(value.get(key, 0)/.2) for key in ("low_rad", "high_rad")]
                               for name, value in packet["motion"]["joints"].items()}
    signal["disagreement"] = gate["measurement_conflicts"]
    return sha256(compact(signal).encode()).hexdigest()


def review_profile(snapshot, gate):
    packet = evidence_packet(snapshot, gate)
    categorical = {key: packet[key] for key in ("structure_id", "measurement", "camera_view", "pose_quality")}
    categorical["view_scope"] = {key:packet["capture_view_policy"].get(key) for key in ("profile","status","supported_observations")}
    categorical["recognition"] = {key: packet["recognition"][key] for key in ("recognized_exercise", "recognition_status")}
    categorical["gate"] = {key: gate[key] for key in ("handoff_allowed", "missing_joints", "motion_supported", "measurement_conflicts")}
    categorical["violations"] = sorted((str(v["type"]), str(v["severity"])) for v in packet["violations"])
    numeric = {"confidence": (packet["recognition"]["recognition_confidence"], .15)}
    numeric.update({"visibility:"+name: (value, .15) for name, value in packet["visibility"].items()})
    for name, value in packet["motion"]["joints"].items():
        for key in ("trimmed_range_rad", "low_rad", "high_rad"):
            numeric[name+":"+key] = (value.get(key, 0), .2)
    return {"categorical": sha256(compact(categorical).encode()).hexdigest(), "numeric": numeric}


def evidence_changed(previous, current):
    if not previous or previous["categorical"] != current["categorical"]:
        return True
    if previous["numeric"].keys() != current["numeric"].keys():
        return True
    return any(abs(value-previous["numeric"][key][0]) >= threshold
               for key, (value, threshold) in current["numeric"].items())

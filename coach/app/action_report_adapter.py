"""Translate the inspected Agent A v1 contract without inventing observations."""
import math
from datetime import datetime, timezone
from app.engine import InputError

EXERCISES = {"squat":"bodyweight_squat", "pushup":"push_up", "plank":"forearm_plank", "bicep_curl":"bicep_curl", "alternate_bicep_curl":"alternate_bicep_curl"}
VIEWS = {"frontal":"front", "profile_left":"side", "profile_right":"side", "three_quarter":"oblique", "auto":"unknown"}
JOINTS = {
    "left_knee":"left_knee_flexion", "right_knee":"right_knee_flexion",
    "left_elbow":"left_elbow_flexion", "right_elbow":"right_elbow_flexion",
    "left_hip":"left_hip_flexion", "right_hip":"right_hip_flexion",
    "left_shoulder":"left_shoulder_segment_angle", "right_shoulder":"right_shoulder_segment_angle",
    "torso_angle":"trunk_inclination",
}
RELEVANT = {
    "squat": {"left_knee","right_knee","left_hip","right_hip","torso_angle"},
    "pushup": {"left_elbow","right_elbow","left_hip","right_hip","torso_angle"},
    "plank": {"left_elbow","right_elbow","left_hip","right_hip","torso_angle"},
    "bicep_curl": {"left_elbow","right_elbow","left_shoulder","right_shoulder","torso_angle"},
    "alternate_bicep_curl": {"left_elbow","right_elbow","left_shoulder","right_shoulder","torso_angle"},
}


def report_from(payload):
    if not isinstance(payload, dict):
        raise InputError("A 组报告必须是对象。")
    report = payload.get("action_report", payload)
    if not isinstance(report, dict) or report.get("schema_version") != "v1":
        raise InputError("需要 A 组 ActionReport v1 或包含 action_report 的响应。")
    return report


def normalize(payload):
    report = report_from(payload)
    exercise = report.get("recognized_exercise")
    if not isinstance(exercise, str):
        raise InputError("recognized_exercise 必须是字符串。")
    if not isinstance(report.get("session_id"), str) or not report["session_id"].strip():
        raise InputError("session_id 必须是非空字符串。")
    if not isinstance(report.get("camera_view", "unknown"), str):
        raise InputError("camera_view 必须是字符串。")
    context = payload.get("context", {})
    if not isinstance(context, dict):
        raise InputError("context 必须是对象。")
    if report.get("recognition_status") != "confirmed" or exercise not in EXERCISES:
        raise InputError("A 组尚未确认支持的运动；暂不调用专项专家。")
    perception = report.get("perception_agent", {})
    if not isinstance(perception, dict):
        raise InputError("perception_agent 必须是对象。")
    if perception and perception.get("handoff_allowed") is not True:
        raise InputError("A Agent 尚未允许交接，需补充动作证据。")
    metrics = report.get("metrics", {})
    if not isinstance(metrics, dict) or not isinstance(metrics.get("joint_angles", {}), dict):
        raise InputError("A 组 metrics/joint_angles 必须是对象。")
    stamp = report.get("timestamp_ms")
    if type(stamp) not in {int,float} or not math.isfinite(stamp):
        raise InputError("timestamp_ms 必须是有限数值。")
    if stamp < 1_000_000_000_000:
        raise InputError("timestamp_ms 需要 Unix 毫秒；视频相对时间应单独记录。")
    try:
        timestamp = datetime.fromtimestamp(stamp/1000, timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        raise InputError("timestamp_ms 超出有效范围。") from None
    confidence = metrics.get("joint_confidences", {})
    if not isinstance(confidence, dict):
        raise InputError("joint_confidences 必须是对象。")
    # Older A reports lack per-angle confidence. Do not substitute recognition confidence.
    fallback = payload.get("form_confidence", 0.0)
    joints = {}
    for name, value in metrics.get("joint_angles", {}).items():
        if name not in RELEVANT[exercise]:
            continue
        joint_confidence = confidence.get(name, fallback)
        if type(joint_confidence) not in {int, float} or not 0 <= joint_confidence <= 1:
            raise InputError(f"joint_confidences.{name} 必须在 0 到 1 之间。")
        joints[JOINTS[name]] = {"angle_deg":value, "confidence":joint_confidence,
                               "definition":"inclination_from_vertical" if name == "torso_angle" else "included_segment_angle"}
    view = VIEWS.get(report.get("camera_view"), report.get("camera_view", "unknown"))
    metadata = {"camera_view":view, "measurement_space":"3d", "calibrated":False,
                "angle_convention":"included_segment_angle", "classification_confidence":report.get("recognition_confidence",0),
                "hold_duration_seconds":metrics.get("hold_seconds",0), "pose_quality":report.get("pose_quality", "unreliable"),
                "measurement_method":"MediaPipe normalized xyz estimates; 3D angles are not calibrated world-coordinate measurements",
                "confidence_method":metrics.get("confidence_method", "legacy aggregate form confidence or missing"),
                "upstream_schema":"agent-a/v1"}
    kinematics = report.get("kinematics", {})
    if not isinstance(kinematics, dict):
        raise InputError("kinematics 必须是对象。")
    if kinematics:
        metadata["capture_view_policy"] = kinematics.get("capture_view_policy", {})
        metadata["kinematic_coordinate_space"] = kinematics.get("coordinate_space", "unknown")
        metadata["measurement_method"] = "Mixed estimates: elbow/knee from fitted URDF bend states; other segment angles from normalized image geometry; neither externally calibrated"
        metadata["joint_measurement_methods"] = {JOINTS[name]:kinematics.get("coordinate_space", "unknown")
                                                for name in RELEVANT[exercise] if name+"_joint" in kinematics.get("joint_states", {})}
    if report.get("pose_quality") == "unreliable":
        for joint in joints.values():
            joint["confidence"] = 0.0
    return {"schema_version":"1.0", "session_id":report.get("session_id"), "timestamp":timestamp,
            "exercise_id":EXERCISES[exercise], "rep_index":report.get("repetition",0),
            "phase":{"eccentric":"descent","concentric":"ascent","hold":"hold","bottom":"bottom","setup":"unknown","idle":"unknown"}.get(report.get("phase"),"unknown"),
            "joints":joints, "metadata":metadata, "reported_symptoms":payload.get("reported_symptoms", []),
            "context":{**context, "agent_a_observations":{"violations":report.get("violations",[]), "agent_context":report.get("agent_context",{}), "metrics":metrics,
                       "kinematics":report.get("kinematics",{}), "perception_agent":perception},
                       "evidence_boundary":"A 的姿势阈值、rep_quality、疲劳代理指标是上游算法观察，不是临床结论。不得将肩骨段夹角改称肩屈曲。"},
            **({"user_id":payload["user_id"]} if payload.get("user_id") else {})}

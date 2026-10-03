"""Bounded model tool loop over immutable measured evidence."""

from collections import deque
from copy import deepcopy
import json
from pathlib import Path
from xml.etree import ElementTree as ET
import time
import math
import numpy as np
from pipeline.kalman import KalmanPoseTracker

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from app.model_client import ModelClient, ModelError
from app.agent_tools import load_skill
from kinematics.fitting import SkeletonFitter
from kinematics.urdf_loader import parse_urdf
from perception.evidence import compact, evidence_packet, review_profile, evidence_changed
from perception.views import view_policy

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = {
    "squat": ["left_knee_joint", "right_knee_joint"],
    "pushup": ["left_elbow_joint", "right_elbow_joint"],
    "plank": ["left_elbow_joint", "right_elbow_joint"],
    "bicep_curl": ["left_elbow_joint", "right_elbow_joint"],
    "alternate_bicep_curl": ["left_elbow_joint", "right_elbow_joint"],
}
TOOLS = ("inspect_urdf", "inspect_motion", "inspect_recognition", "inspect_visibility")


def snapshot_from_report(report):
    """Reconstruct/validate the parsed structure for portable JSON review."""
    kin = report.kinematics
    structure, states, motion = kin.get("structure"), kin.get("joint_states"), kin.get("motion_evidence")
    if not isinstance(structure, dict) or not structure or len(structure) > 100:
        raise ValueError("Parsed URDF structure is required (maximum 100 joints)")
    if not isinstance(states, dict) or not isinstance(motion, dict):
        raise ValueError("Measured joint states and motion_evidence are required")
    root = ET.Element("robot", name="imported_observed_skeleton")
    links = set()
    for name, spec in structure.items():
        if not isinstance(spec, dict) or not isinstance(name, str):
            raise ValueError("Invalid URDF joint structure")
        parent, child, kind = spec.get("parent"), spec.get("child"), spec.get("type")
        if not all(isinstance(v, str) and v for v in (parent, child, kind)):
            raise ValueError("Missing URDF parent/child/type")
        links.update((parent, child))
        j = ET.SubElement(root, "joint", name=name, type=kind)
        ET.SubElement(j, "parent", link=parent)
        ET.SubElement(j, "child", link=child)
        def vector(key, default):
            values = spec.get(key, default)
            if not isinstance(values, list) or len(values) != 3 or any(type(v) not in {int,float} or not math.isfinite(v) for v in values):
                raise ValueError("Invalid URDF vector")
            return " ".join(str(v) for v in values)
        ET.SubElement(j, "origin", xyz=vector("origin_xyz", [0,0,0]), rpy=vector("origin_rpy", [0,0,0]))
        ET.SubElement(j, "axis", xyz=vector("axis", [1,0,0]))
        if kind != "fixed":
            limits = {"effort": "1", "velocity": "20"}
            for key in ("lower", "upper"):
                if spec.get(key) is not None:
                    if type(spec[key]) not in {int,float} or not math.isfinite(spec[key]):
                        raise ValueError("Invalid URDF limit")
                    limits[key] = str(spec[key])
            ET.SubElement(j, "limit", **limits)
    for name in sorted(links):
        ET.SubElement(root, "link", name=name)
    xml = ET.tostring(root, encoding="unicode")
    model = parse_urdf(xml)
    for name, state in states.items():
        if name not in model.joints or not isinstance(state, dict):
            raise ValueError("Unknown joint state")
        for key, low, high in (("position_rad", 0, math.pi), ("visibility", 0, 1)):
            value = state.get(key)
            if type(value) not in {int,float} or not math.isfinite(value) or not low <= value <= high:
                raise ValueError("Invalid measured joint state")
    for key in ("frames", "duration_seconds"):
        value = motion.get(key)
        if type(value) not in {int,float} or not math.isfinite(value) or value < 0:
            raise ValueError("Invalid motion summary")
    if not isinstance(motion.get("joints"), dict):
        raise ValueError("Motion joint summaries are required")
    for name, data in motion["joints"].items():
        if name not in model.joints or not isinstance(data, dict):
            raise ValueError("Invalid motion joint")
        for key in ("samples", "trimmed_range_rad"):
            value = data.get(key)
            if type(value) not in {int,float} or not math.isfinite(value) or value < 0:
                raise ValueError("Invalid motion evidence")
    return {"action_report": report.model_dump(), "urdf_xml": xml, "motion": motion, "generation": 0}


class ToolChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: Literal["inspect_urdf", "inspect_motion", "inspect_recognition", "inspect_visibility", "finish"]
    decision: Literal["observe", "request_view", "handoff"] = "observe"
    reason: str = Field(default="", max_length=500)
    observation_request: Literal["none", "show_full_body", "side_view", "continue_motion"] = "none"


class PerceptionSession:
    def __init__(self):
        self.fitter = SkeletonFitter()
        self.history = deque(maxlen=120)
        self.view_history = deque(maxlen=60)
        self.latest = None
        self.updated_at = 0.0
        self.generation = 0
        self.reviewing = False
        self.coaching = False
        self.last_review_at = 0.0
        self.review_result = None
        self.world_tracker = KalmanPoseTracker()
        self.review_revision = 0
        self.last_signature = None
        self.profile_anchor = None
        self.review_baseline = None
        self.review_cached_at = 0.0
        self.summary = None
        self.last_input_timestamp_ms = None
        self.frame_buffer = deque(maxlen=2400)
        self.buffer_dropped = 0
        self.buffer_rejected = 0
        self.set_busy = False
        self.completed_set = None
        self.set_snapshots = []

    def update(self, report, filtered_landmarks, world_landmarks=None, capture_profile=None, observed_view=None, requested_view=None, tracking_observations=None):
        discontinuity = self.history and (report.timestamp_ms <= self.history[-1]["timestamp_ms"] or
                                         report.timestamp_ms-self.history[-1]["timestamp_ms"] > 750)
        if discontinuity:
            self.view_history.clear()
            self.world_tracker.reset()
            self.fitter = SkeletonFitter()
            self.history.clear()
            self.review_revision += 1
            self.profile_anchor = None
            self.summary = None
        coordinate_space = "image_width_normalized"
        fit_points = filtered_landmarks
        world_status = "not_supplied"
        if filtered_landmarks and isinstance(world_landmarks, list) and len(world_landmarks) == 33:
            try:
                world = np.asarray([[p["x"], p["y"], p["z"], p.get("visibility", 0)] for p in world_landmarks], dtype=float)
                if not np.isfinite(world).all() or np.max(np.abs(world[:, :3])) > 10:
                    raise ValueError("Invalid world coordinates")
                world[:, 3] = np.minimum(np.clip(world[:, 3], 0, 1), np.asarray(filtered_landmarks)[:, 3])
                if min(world[23,3], world[24,3]) < .6:
                    raise ValueError("World pelvis not visible")
                xyz, _ = self.world_tracker.update(world, report.timestamp_ms/1000)
                fit_points = np.column_stack((xyz, world[:, 3])).tolist()
                coordinate_space = "mediapipe_world"
                world_status = "used"
            except (ValueError, KeyError, TypeError):
                world_status = "invalid_fallback_image"
                self.world_tracker.reset()
        else:
            self.world_tracker.reset()
        if self.fitter.coordinate_space != coordinate_space:
            self.history.clear()
        kinematics = self.fitter.update(fit_points, report.timestamp_ms, coordinate_space)
        kinematics["world_input_status"] = world_status
        if tracking_observations:
            kinematics["tracking_observations"] = tracking_observations
            kinematics["tracking_summary"] = {"filtered_observations":sum(p["source"]=="filtered_observation" for p in tracking_observations),
                "prediction_only":sum(p["source"]=="prediction_only" for p in tracking_observations),
                "low_confidence_estimates":sum(p["source"]=="low_confidence_model_estimate" for p in tracking_observations),
                "method":"constant_velocity_Kalman; covariance_not_calibrated_error_probability",
                "prediction_policy":"do_not_use_prediction_only_points_to_confirm_cycles_or_form_errors"}
        self.view_history.append((report.timestamp_ms, observed_view or "unknown"))
        views = [view for stamp, view in self.view_history if 0 <= report.timestamp_ms-stamp <= 600]
        # Require temporal agreement; a declared view never participates in the vote.
        winner = max(set(views), key=views.count)
        stable_view = winner if len(views) >= 3 and views.count(winner)/len(views) >= .7 else "unknown"
        report.camera_view = stable_view
        kinematics["capture_view_policy"] = view_policy(report.recognized_exercise, capture_profile, stable_view, requested_view)
        kinematics["capture_view_policy"].update({"instantaneous_view":observed_view or "unknown",
                                                "window_ms":600, "agreement":views.count(winner)/len(views)})
        report.kinematics = kinematics
        disagreements = {}
        # URDF joint names, units and q definitions are authoritative for these
        # four proxies. Keep the old included-angle contract for B consumers.
        for name, value in kinematics.get("joint_states", {}).items():
            short = name.removesuffix("_joint")
            if coordinate_space == "mediapipe_world" and short in report.metrics.joint_angles:
                disagreements[short] = abs(report.metrics.joint_angles[short] - (180-math.degrees(value["position_rad"])))
            report.metrics.joint_angles[short] = round(180 - math.degrees(value["position_rad"]), 2)
            report.metrics.joint_confidences[short] = value["visibility"]
        kinematics["image_world_angle_disagreement_deg"] = disagreements
        self.updated_at = time.monotonic()
        if not kinematics.get("joint_states"):
            self.history.clear()
        if self.history and report.timestamp_ms <= self.history[-1]["timestamp_ms"]:
            self.history.clear()
        self.history.append({"timestamp_ms": report.timestamp_ms,
                             "joint_states": deepcopy(kinematics.get("joint_states", {})),
                             "disagreements": disagreements,
                             "exercise": report.recognized_exercise})
        recent = list(self.history)[-8:]
        kinematics["persistent_measurement_conflicts"] = [name for name in disagreements
            if sum(frame.get("disagreements", {}).get(name, 0) >= 25 for frame in recent) >= 5]
        snapshot = {"action_report": report.model_dump(), "motion": self.motion_summary(),
                    "urdf_xml": self.fitter.xml, "generation": self.generation}
        report.kinematics["motion_evidence"] = snapshot["motion"]
        policy = self.policy(snapshot)
        profile = review_profile(snapshot, policy)
        if evidence_changed(self.profile_anchor, profile):
            self.review_revision += 1
            self.profile_anchor = profile
            if (self.summary and (self.summary["exercise"] != report.recognized_exercise or
                                  not policy["handoff_allowed"])):
                self.summary = None
        report.perception_agent = policy
        report.agent_context.should_coach_now &= policy["handoff_allowed"]
        self.latest = {**snapshot, "action_report": report.model_dump(), "review_revision": self.review_revision,
                       "session_summary": self.summary}
        return policy

    def motion_summary(self):
        if not self.history:
            return {"frames": 0, "duration_seconds": 0, "joints": {}}
        end = self.history[-1]["timestamp_ms"]
        frames = [frame for frame in self.history if 0 <= end-frame["timestamp_ms"] <= 6000]
        result = {}
        names = set(self.history[-1]["joint_states"])
        for name in names:
            values = [f["joint_states"][name]["position_rad"] for f in frames if name in f["joint_states"]]
            ordered = sorted(values)
            if len(values) >= 5:
                lo, hi = ordered[int((len(values)-1)*.1)], ordered[int((len(values)-1)*.9)]
            else:
                lo = hi = values[-1]
            result[name] = {"samples": len(values), "trimmed_range_rad": hi-lo,
                            "low_rad": lo, "high_rad": hi,
                            "latest_rad": values[-1]}
        return {"frames": len(frames), "duration_seconds": (end-frames[0]["timestamp_ms"])/1000,
                "joints": result}

    @staticmethod
    def policy(snapshot):
        report = snapshot["action_report"]
        kin = report["kinematics"]
        exercise = report["recognized_exercise"]
        required = REQUIRED.get(exercise, [])
        # A profile observation supports only the visible limb, never bilateral claims.
        observed = kin.get("capture_view_policy", {}).get("estimated_view")
        if observed in {"profile_left", "profile_right"} and exercise != "alternate_bicep_curl":
            visible = [key for key in required if kin.get("joint_states", {}).get(key, {}).get("visibility", 0) >= .6]
            if visible:
                required = [max(visible, key=lambda key: kin["joint_states"][key]["visibility"])]
        missing = [key for key in required if key not in kin.get("joint_states", {})]
        motion = snapshot.get("motion", {})
        relevant = [motion.get("joints", {}).get(key, {}) for key in required]
        motion_supported = (motion.get("duration_seconds", 0) >= .4 and
                            any(j.get("samples", 0) >= 5 and j.get("trimmed_range_rad", 0) >= .08 for j in relevant))
        if exercise == "plank":
            motion_supported = motion.get("duration_seconds", 0) >= .4
        allowed = (report["recognition_status"] == "confirmed" and report["pose_quality"] != "unreliable"
                   and exercise in REQUIRED and not missing and kin.get("status") == "available" and motion_supported)
        conflicts = kin.get("persistent_measurement_conflicts")
        if not isinstance(conflicts, list):
            conflicts = [name for name, value in kin.get("image_world_angle_disagreement_deg", {}).items() if value >= 25]
        conflicts = [name for name in conflicts if name+"_joint" in required]
        if conflicts:
            allowed = False
        view_policy=kin.get("capture_view_policy",{})
        view_blocked=view_policy.get("profile") in {"frontal_v1", "exercise_view_v1"} and view_policy.get("status")!="supported"
        if view_blocked:
            allowed=False
        request = "none" if allowed else "show_full_body" if kin.get("status") != "available" or missing else "continue_motion"
        if conflicts:
            request = "side_view"
        if view_blocked:
            request="side_view" if view_policy.get("preferred_view")=="side" else "show_full_body"
        return {"mode": "local_policy", "model_called": False, "skill": "perception-urdf",
                "decision": "handoff" if allowed else "request_view" if request == "show_full_body" else "observe",
                "handoff_allowed": allowed, "missing_joints": missing, "observation_request": request,
                "required_observed_joints":required,
                "motion_supported": motion_supported,
                "measurement_conflicts": conflicts,
                "view_requirement_satisfied":not view_blocked,
                "reason": "证据检查通过；测量仍未经标定，专家需按观测限制评价。" if allowed else "当前视角未支持该动作的观测规范，请参照该动作拍摄要求；声明视角不能替代观测验证。" if view_blocked else "需要可靠动作识别、可见关节和连续运动证据。",
                "tools": ["fit_skeleton", "parse_urdf", "forward_kinematics", "visibility_gate", "recognition_gate"]}

    def snapshot(self):
        if self.latest is None or time.monotonic()-self.updated_at > 10:
            raise ValueError("No fresh pose; start video or camera first")
        return deepcopy(self.latest)

    def reset(self, clear_buffer=True):
        if clear_buffer:
            self.frame_buffer.clear()
            self.buffer_dropped = self.buffer_rejected = 0
            self.completed_set = None
            self.set_snapshots = []
        self.last_input_timestamp_ms = None
        self.fitter = SkeletonFitter()
        self.history.clear()
        self.view_history.clear()
        self.latest = None
        self.updated_at = 0
        self.generation += 1
        self.review_result = None
        self.world_tracker.reset()
        self.review_revision += 1
        self.last_signature = None
        self.profile_anchor = None
        self.review_baseline = None
        self.review_cached_at = 0
        self.summary = None

    def cached_review(self, snapshot):
        if (not self.review_result or self.review_result.get("status") != "completed" or
                time.monotonic()-self.review_cached_at > 45 or
                self.review_baseline != snapshot.get("review_revision")):
            return None
        result = deepcopy(self.review_result)
        review = result["perception_agent"]
        gate = self.policy(snapshot)
        review.update({"cache_hit": True, "model_called": False, "model_calls": 0,
                       "reused_from_timestamp_ms": review["timestamp_ms"],
                       "timestamp_ms": snapshot["action_report"]["timestamp_ms"], "gate": gate})
        review["optimization"] = {"cache_hit": True, "model_calls": 0, "input_chars_total": 0,
                                  "usage_total": {}, "source_review": review.get("optimization", {})}
        review["handoff_allowed"] &= gate["handoff_allowed"]
        result["action_report"] = {**snapshot["action_report"], "perception_agent": review}
        result["motion"] = snapshot["motion"]
        return result


class PerceptionAgent:
    def __init__(self, client=None):
        self.client = client or ModelClient()

    @staticmethod
    def tool(name, snapshot):
        report = snapshot["action_report"]
        if name == "inspect_urdf":
            if not snapshot["urdf_xml"]:
                return {"status": "parsed_json", "structure": report["kinematics"].get("structure", {}),
                        "kinematics": report["kinematics"]}
            model = parse_urdf(snapshot["urdf_xml"])
            return {"name": model.name, "joints": model.compact_joint_map(),
                    "kinematics": report["kinematics"]}
        if name == "inspect_motion":
            return snapshot["motion"]
        if name == "inspect_visibility":
            return {"pose_quality": report["pose_quality"], "camera_view": report["camera_view"],
                    "visibility": report["metrics"]["joint_confidences"],
                    "gate": PerceptionSession.policy(snapshot)}
        if name == "inspect_recognition":
            return {key: report[key] for key in ("recognition_status", "recognized_exercise", "recognition_confidence", "candidate_exercises", "phase", "repetition")}
        raise ValueError("Unknown tool")

    def run(self, snapshot):
        skill = load_skill("perception-urdf")
        started = time.perf_counter()
        gate = PerceptionSession.policy(snapshot)
        # Execute mandatory inspection locally once, then send one evidence pack.
        if snapshot.get("urdf_xml"):
            parse_urdf(snapshot["urdf_xml"])
        packet = evidence_packet(snapshot, gate)
        messages = [{"role": "system", "content": skill + "\nOutput schema: " + compact(ToolChoice.model_json_schema())},
                    {"role": "user", "content": compact({"evidence": packet, "session_summary": snapshot.get("session_summary")})}]
        trace = [{"step": 0, "tool": name, "status": "precomputed"} for name in TOOLS]
        metadata, totals = {}, {}
        input_chars, calls = 0, 0
        choice = None
        requested = set()
        for step in range(3):
            input_chars += sum(len(message["content"]) for message in messages)
            content, metadata = self.client.complete(messages)
            calls += 1
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = metadata.get("usage", {}).get(key)
                if type(value) is int:
                    totals[key] = totals.get(key, 0) + value
            try:
                choice = ToolChoice.model_validate_json(content)
            except ValueError as exc:
                raise ModelError("A Agent returned invalid tool/decision JSON") from exc
            messages.append({"role": "assistant", "content": content})
            if choice.tool == "finish":
                break
            if choice.tool in requested:
                raise ModelError("A Agent repeated a tool; bounded loop stopped")
            requested.add(choice.tool)
            observation = self.tool(choice.tool, snapshot)
            # Additional detail replaces the prior user evidence instead of growing
            # a transcript that recursively repeats report/kinematics/context.
            messages = [messages[0], {"role": "user", "content": compact({"evidence": packet,
                        "requested_tool": choice.tool, "tool_result": observation,
                        "remaining_calls": 2-step, "session_summary": snapshot.get("session_summary")})}]
        if choice is None or choice.tool != "finish":
            raise ModelError("A Agent exceeded its tool budget")
        inspected = {item["tool"] for item in trace}
        required_tools = {"inspect_visibility", "inspect_recognition", "inspect_urdf"}
        if snapshot["action_report"]["recognized_exercise"] != "plank":
            required_tools.add("inspect_motion")
        # LLM may withhold a handoff, but cannot promote uncertain recognition.
        allowed = gate["handoff_allowed"] and choice.decision == "handoff" and required_tools <= inspected
        review = {"mode": "ai_agent", "model_called": True, "skill": "perception-urdf",
                  "decision": "handoff" if allowed else "observe" if choice.decision == "handoff" else choice.decision,
                  "handoff_allowed": allowed, "reason": choice.reason,
                  "observation_request": choice.observation_request if choice.decision != "handoff" else gate["observation_request"],
                  "trace": trace, "gate": gate, "timestamp_ms": snapshot["action_report"]["timestamp_ms"], **metadata}
        review["optimization"] = {"evidence_chars": len(compact(packet)),
                                  "full_report_chars": len(compact(snapshot["action_report"])),
                                  "input_chars_total": input_chars, "model_calls": calls,
                                  "latency_ms": round((time.perf_counter()-started)*1000),
                                  "usage_total": totals, "cache_hit": False}
        review.update({"model_calls": calls, "cache_hit": False})
        return {"perception_agent": review, "action_report": {**snapshot["action_report"], "perception_agent": review},
                "motion": snapshot["motion"]}

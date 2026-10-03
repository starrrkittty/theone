"""Reduced observed skeleton snapshots, with explicit non-metric provenance."""

from collections import deque
from hashlib import sha256
from xml.etree import ElementTree as ET
import warnings

import numpy as np
from scipy.spatial.transform import Rotation

from kinematics.urdf_loader import parse_urdf, parser_backend

LIMBS = {
    "left_elbow": (11, 13, 15), "right_elbow": (12, 14, 16),
    "left_knee": (23, 25, 27), "right_knee": (24, 26, 28),
}


def forward_kinematics(model, positions):
    root = next(iter(model.links - {j.child for j in model.joints.values()}))
    poses = {root: np.eye(4)}
    pending = list(model.joints.values())
    while pending:
        for joint in list(pending):
            if joint.parent not in poses:
                continue
            origin = np.eye(4)
            origin[:3, :3] = Rotation.from_euler("xyz", joint.origin_rpy).as_matrix()
            origin[:3, 3] = joint.origin_xyz
            motion = np.eye(4)
            q = positions.get(joint.name, 0.0)
            axis = np.asarray(joint.axis, dtype=float)
            if joint.joint_type != "fixed":
                axis /= np.linalg.norm(axis)
            if joint.joint_type in {"revolute", "continuous"}:
                motion[:3, :3] = Rotation.from_rotvec(axis * q).as_matrix()
            elif joint.joint_type == "prismatic":
                motion[:3, 3] = axis * q
            poses[joint.child] = poses[joint.parent] @ origin @ motion
            pending.remove(joint)
    return poses


class SkeletonFitter:
    def __init__(self):
        self.lengths = {name: deque(maxlen=30) for name in LIMBS}
        self.previous = {}
        self.previous_time = None
        self.xml = None
        self.latest = None
        self.coordinate_space = None

    def update(self, landmarks, timestamp_ms, coordinate_space="image_width_normalized"):
        if self.coordinate_space != coordinate_space:
            self.coordinate_space = coordinate_space
            for values in self.lengths.values():
                values.clear()
            self.previous = {}
            self.previous_time = None
        if not landmarks or len(landmarks) != 33:
            for values in self.lengths.values():
                values.clear()
            self.previous = {}
            self.previous_time = None
            self.latest = {"status": "unavailable", "joint_states": {}, "reason": "missing_pose"}
            self.xml = None
            return self.latest
        points = np.asarray(landmarks, dtype=float)
        if points.shape != (33, 4) or not np.isfinite(points).all():
            return self.update([], timestamp_ms, coordinate_space)
        visible_hips = [index for index in (23,24) if points[index,3] >= .6]
        if not visible_hips:
            return self.update([], timestamp_ms, coordinate_space)
        pelvis = points[visible_hips, :3].mean(axis=0)
        root = ET.Element("robot", name="observed_human_reduced_v1")
        root.append(ET.Comment("Learned world estimates in meters, not calibrated measurements." if coordinate_space == "mediapipe_world" else "Normalized image-width origins, NOT SI meters. Requires scale calibration."))
        ET.SubElement(root, "link", name="pelvis")
        states, targets, quality = {}, {}, {}
        for name, (a, b, c) in LIMBS.items():
            confidence = float(min(points[[a, b, c], 3]))
            if confidence < .6:
                continue
            proximal = points[b, :3] - points[a, :3]
            distal = points[c, :3] - points[b, :3]
            upper, lower = np.linalg.norm(proximal), np.linalg.norm(distal)
            if min(upper, lower) < 1e-5:
                continue
            self.lengths[name].append((upper, lower))
            length1, length2 = np.median(self.lengths[name], axis=0)
            z = proximal / upper
            v = distal / lower
            q = float(np.arccos(np.clip(z @ v, -1, 1)))
            x = v - z * (z @ v)
            if np.linalg.norm(x) < 1e-5:
                helper = np.eye(3)[np.argmin(np.abs(z))]
                x = helper - z * (z @ helper)
            x /= np.linalg.norm(x)
            y = np.cross(z, x)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                rpy = Rotation.from_matrix(np.column_stack((x, y, z))).as_euler("xyz")
            prefix = name + "_"
            for link in ("proximal", "distal", "tip"):
                ET.SubElement(root, "link", name=prefix + link)
            self._joint(root, prefix + "anchor", "fixed", "pelvis", prefix + "proximal", points[a, :3] - pelvis, rpy)
            joint_name = name + "_joint"
            self._joint(root, joint_name, "revolute", prefix + "proximal", prefix + "distal", (0, 0, length1))
            self._joint(root, prefix + "endpoint", "fixed", prefix + "distal", prefix + "tip", (0, 0, length2))
            dt = (timestamp_ms - self.previous_time) / 1000 if self.previous_time is not None else 0
            velocity = (q - self.previous[name]) / dt if name in self.previous and .01 <= dt <= .5 else None
            states[joint_name] = {"position_rad": q, "velocity_rad_s": velocity,
                                  "visibility": confidence, "definition": "unsigned_bend_proxy"}
            targets[prefix + "tip"] = points[c, :3] - pelvis
            quality[name] = {"samples": len(self.lengths[name]), "lengths": [float(length1), float(length2)]}
        self.xml = ET.tostring(root, encoding="unicode")
        model = parse_urdf(self.xml)
        fk = forward_kinematics(model, {k: v["position_rad"] for k, v in states.items()})
        errors = {name: float(np.linalg.norm(fk[name][:3, 3] - target)) for name, target in targets.items()}
        self.previous = {key.removesuffix("_joint"): value["position_rad"] for key, value in states.items()}
        self.previous_time = timestamp_ms
        self.latest = {
            "status": "available" if states else "insufficient_visibility", "timestamp_ms": timestamp_ms,
            "model_id": sha256(self.xml.encode()).hexdigest()[:16], "parser": parser_backend(),
            "model_kind": "per_frame_reduced_skeleton", "coordinate_space": coordinate_space,
            "coordinate_units": "estimated_meters" if coordinate_space == "mediapipe_world" else "image_width_normalized_not_meters",
            "metric_calibrated": False, "base_position": pelvis.tolist(), "joint_states": states,
            "base_reference":"bilateral_hip_midpoint" if len(visible_hips)==2 else "visible_hip_anchor_not_pelvis_center",
            "structure": model.compact_joint_map(),
            "fit": quality, "fk_endpoint_residuals": errors,
            "residual_units": "estimated_meters" if coordinate_space == "mediapipe_world" else "image_width_normalized",
            "limitations": ["World estimates are learned, not externally calibrated." if coordinate_space == "mediapipe_world" else "URDF origins use normalized lengths; convert with calibrated scale before robotics use.",
                            "Proximal orientation is refitted each frame; not a fixed anatomical shoulder/hip model.",
                            "Hinge bend proxies omit axial rotation, joint translation and anatomical calibration.",
                            "Low visibility limbs are omitted; residuals check internal fit, not real-world accuracy."],
        }
        return self.latest

    @staticmethod
    def _joint(root, name, kind, parent, child, xyz, rpy=(0, 0, 0)):
        joint = ET.SubElement(root, "joint", name=name, type=kind)
        ET.SubElement(joint, "parent", link=parent)
        ET.SubElement(joint, "child", link=child)
        ET.SubElement(joint, "origin", xyz=" ".join(str(float(v)) for v in xyz), rpy=" ".join(str(float(v)) for v in rpy))
        if kind == "revolute":
            ET.SubElement(joint, "axis", xyz="0 1 0")
            # Geometric proxy domain, not an exercise target or medical limit.
            ET.SubElement(joint, "limit", lower="0", upper=str(float(np.pi)), effort="1", velocity="20")

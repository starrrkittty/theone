"""Static yoga pose detection with hold-oriented form feedback.

This module is **independent of** ``BaseExercise`` (which is built around
counting flex-extend rep cycles). Yoga poses are *held*, not repeated, so each
pose simply answers, per frame: "is the body in this pose right now, and if not,
what should the user fix?" Hold timing lives in ``pipeline/hold_timer.py``;
session orchestration lives in ``state_machine/yoga_manager.py``.

Geometry reuses the shared helpers/types from ``exercises.base``
(``calculate_angle``, ``Landmark``, ``JointName``, ``landmarks_to_dict``).

Detection notes
---------------
Standing poses (Mountain, Tree, Warrior I/II, Chair, Triangle) are designed for
a **front-facing** camera. Floor/inverted poses (Downward Dog, Cobra) need a
**side** view and use deliberately lenient thresholds — phone-camera pose
estimation of floor poses is noisy. Thresholds are class constants so they are
easy to tune against real footage.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

from config.settings import settings

from .base import (
    JointName,
    Landmark,
    calculate_angle,
    landmarks_to_dict,
)

# Joints below this visibility are treated as not reliably detected.
VISIBILITY_THRESHOLD = 0.3


@dataclass
class YogaEvaluation:
    """Per-frame assessment of a single yoga pose."""
    is_in_pose: bool
    violations: list[str] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)
    joint_colors: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0


# --------------------------------------------------------------------------- #
# Geometry helpers
# --------------------------------------------------------------------------- #

def _mid(a: Landmark, b: Landmark) -> tuple[float, float]:
    return ((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)


def _angle_from_vertical(top: tuple[float, float], bottom: tuple[float, float]) -> float:
    """Angle in degrees between the segment bottom->top and straight up.

    0° = perfectly vertical (top directly above bottom); 90° = horizontal.
    """
    seg = np.array([top[0] - bottom[0], top[1] - bottom[1]])
    n = np.linalg.norm(seg)
    if n == 0:
        return 0.0
    up = np.array([0.0, -1.0])  # image y grows downward, so "up" is -y
    cos = np.clip(np.dot(seg, up) / n, -1.0, 1.0)
    return float(np.degrees(np.arccos(cos)))


def _knee_angle(lm: dict[JointName, Landmark], side: str) -> float:
    if side == "left":
        return calculate_angle(lm[JointName.LEFT_HIP], lm[JointName.LEFT_KNEE], lm[JointName.LEFT_ANKLE])
    return calculate_angle(lm[JointName.RIGHT_HIP], lm[JointName.RIGHT_KNEE], lm[JointName.RIGHT_ANKLE])


def _elbow_angle(lm: dict[JointName, Landmark], side: str) -> float:
    if side == "left":
        return calculate_angle(lm[JointName.LEFT_SHOULDER], lm[JointName.LEFT_ELBOW], lm[JointName.LEFT_WRIST])
    return calculate_angle(lm[JointName.RIGHT_SHOULDER], lm[JointName.RIGHT_ELBOW], lm[JointName.RIGHT_WRIST])


def _hip_pike_angle(lm: dict[JointName, Landmark], side: str) -> float:
    """Angle at the hip (shoulder-hip-knee) — the apex of a Downward Dog 'V'."""
    if side == "left":
        return calculate_angle(lm[JointName.LEFT_SHOULDER], lm[JointName.LEFT_HIP], lm[JointName.LEFT_KNEE])
    return calculate_angle(lm[JointName.RIGHT_SHOULDER], lm[JointName.RIGHT_HIP], lm[JointName.RIGHT_KNEE])


# --------------------------------------------------------------------------- #
# Base pose
# --------------------------------------------------------------------------- #

class BaseYogaPose(ABC):
    """Abstract static-pose detector.

    Subclasses set the class metadata (``name``/``display_name``/``sanskrit``/
    ``camera_view``/``target_hold_seconds``) and implement :meth:`evaluate`.
    """

    name: str = "pose"
    display_name: str = "Pose"
    sanskrit: str = ""
    camera_view: str = "front"  # 'front' | 'side'
    # Subclasses normally override this; the settings value is the fallback for
    # any pose that does not specify its own target hold.
    target_hold_seconds: float = settings.YOGA_DEFAULT_HOLD_SECONDS

    @property
    @abstractmethod
    def required_joints(self) -> list[JointName]:
        ...

    @abstractmethod
    def evaluate(self, lm: dict[JointName, Landmark]) -> YogaEvaluation:
        ...

    # Shared frame entry point used by the YogaManager.
    def process_frame(self, landmarks: list[dict]) -> YogaEvaluation:
        lm = landmarks_to_dict(landmarks)
        missing = [
            j for j in self.required_joints
            if j not in lm or lm[j].visibility < VISIBILITY_THRESHOLD
        ]
        if missing:
            return YogaEvaluation(
                is_in_pose=False,
                violations=["Body not fully visible"],
                corrections=["Step back so your whole body is in the camera frame"],
                joint_colors={},
                confidence=0.0,
            )
        ev = self.evaluate(lm)
        if ev.confidence <= 0.0:
            ev.confidence = self._visibility_confidence(lm)
        return ev

    def _visibility_confidence(self, lm: dict[JointName, Landmark]) -> float:
        vis = [lm[j].visibility for j in self.required_joints if j in lm]
        return float(sum(vis) / len(vis)) if vis else 0.0

    def _green(self) -> dict[str, str]:
        return {j.value: "green" for j in self.required_joints}


# --------------------------------------------------------------------------- #
# Standing poses (front camera)
# --------------------------------------------------------------------------- #

class MountainPose(BaseYogaPose):
    name = "mountain"
    display_name = "Mountain Pose"
    sanskrit = "Tadasana"
    camera_view = "front"
    target_hold_seconds = 15.0

    MIN_LEG_STRAIGHT = 160.0       # knee angle for straight legs
    MAX_TORSO_TILT = 15.0          # degrees from vertical
    MAX_SHOULDER_UNLEVEL = 0.08    # normalized y difference

    @property
    def required_joints(self) -> list[JointName]:
        return [
            JointName.LEFT_SHOULDER, JointName.RIGHT_SHOULDER,
            JointName.LEFT_HIP, JointName.RIGHT_HIP,
            JointName.LEFT_KNEE, JointName.RIGHT_KNEE,
            JointName.LEFT_ANKLE, JointName.RIGHT_ANKLE,
        ]

    def evaluate(self, lm):
        v, c, jc = [], [], self._green()

        left_knee = _knee_angle(lm, "left")
        right_knee = _knee_angle(lm, "right")
        if left_knee < self.MIN_LEG_STRAIGHT or right_knee < self.MIN_LEG_STRAIGHT:
            v.append("Knees are bent")
            c.append("Straighten your legs and stand tall")
            jc[JointName.LEFT_KNEE.value] = "yellow"
            jc[JointName.RIGHT_KNEE.value] = "yellow"

        torso = _angle_from_vertical(
            _mid(lm[JointName.LEFT_SHOULDER], lm[JointName.RIGHT_SHOULDER]),
            _mid(lm[JointName.LEFT_HIP], lm[JointName.RIGHT_HIP]),
        )
        if torso > self.MAX_TORSO_TILT:
            v.append("Leaning to one side")
            c.append("Stack your shoulders over your hips and stand straight")
            jc[JointName.LEFT_SHOULDER.value] = "yellow"
            jc[JointName.RIGHT_SHOULDER.value] = "yellow"

        if abs(lm[JointName.LEFT_SHOULDER].y - lm[JointName.RIGHT_SHOULDER].y) > self.MAX_SHOULDER_UNLEVEL:
            v.append("Shoulders are uneven")
            c.append("Level your shoulders")

        return YogaEvaluation(is_in_pose=not v, violations=v, corrections=c, joint_colors=jc)


class TreePose(BaseYogaPose):
    name = "tree"
    display_name = "Tree Pose"
    sanskrit = "Vrksasana"
    camera_view = "front"
    target_hold_seconds = 20.0

    STANDING_LEG_STRAIGHT = 150.0
    MIN_FOOT_LIFT = 0.12       # raised ankle must be this much higher (smaller y)
    MAX_TORSO_TILT = 22.0

    @property
    def required_joints(self) -> list[JointName]:
        return [
            JointName.LEFT_SHOULDER, JointName.RIGHT_SHOULDER,
            JointName.LEFT_HIP, JointName.RIGHT_HIP,
            JointName.LEFT_KNEE, JointName.RIGHT_KNEE,
            JointName.LEFT_ANKLE, JointName.RIGHT_ANKLE,
        ]

    def evaluate(self, lm):
        v, c, jc = [], [], self._green()

        la = lm[JointName.LEFT_ANKLE]
        ra = lm[JointName.RIGHT_ANKLE]
        # The standing foot is the lower one (larger y); the other should be lifted.
        foot_lift = abs(la.y - ra.y)
        lifted = foot_lift > self.MIN_FOOT_LIFT
        if not lifted:
            v.append("Both feet are on the ground")
            c.append("Lift one foot and place the sole on your inner thigh or calf")
            jc[JointName.LEFT_ANKLE.value] = "yellow"
            jc[JointName.RIGHT_ANKLE.value] = "yellow"
        else:
            # Standing leg should be straight.
            standing = "left" if la.y > ra.y else "right"
            if _knee_angle(lm, standing) < self.STANDING_LEG_STRAIGHT:
                v.append("Standing leg is bent")
                c.append("Straighten and root down through your standing leg")
                jc[(JointName.LEFT_KNEE if standing == "left" else JointName.RIGHT_KNEE).value] = "yellow"

        torso = _angle_from_vertical(
            _mid(lm[JointName.LEFT_SHOULDER], lm[JointName.RIGHT_SHOULDER]),
            _mid(lm[JointName.LEFT_HIP], lm[JointName.RIGHT_HIP]),
        )
        if torso > self.MAX_TORSO_TILT:
            v.append("Losing balance")
            c.append("Engage your core and fix your gaze on one point")
            jc[JointName.LEFT_SHOULDER.value] = "yellow"
            jc[JointName.RIGHT_SHOULDER.value] = "yellow"

        return YogaEvaluation(is_in_pose=not v, violations=v, corrections=c, joint_colors=jc)


class _LungeArmsPose(BaseYogaPose):
    """Shared base for Warrior I / II: a bent front knee + straight back leg.

    Subclasses differ only in the required arm position.
    """

    FRONT_KNEE_MIN = 80.0
    FRONT_KNEE_MAX = 130.0
    BACK_LEG_STRAIGHT = 150.0
    MAX_TORSO_TILT = 30.0

    @property
    def required_joints(self) -> list[JointName]:
        return [
            JointName.LEFT_SHOULDER, JointName.RIGHT_SHOULDER,
            JointName.LEFT_ELBOW, JointName.RIGHT_ELBOW,
            JointName.LEFT_WRIST, JointName.RIGHT_WRIST,
            JointName.LEFT_HIP, JointName.RIGHT_HIP,
            JointName.LEFT_KNEE, JointName.RIGHT_KNEE,
            JointName.LEFT_ANKLE, JointName.RIGHT_ANKLE,
        ]

    def _check_lunge(self, lm, v, c, jc) -> None:
        left_knee = _knee_angle(lm, "left")
        right_knee = _knee_angle(lm, "right")
        bent = min(left_knee, right_knee)
        straight = max(left_knee, right_knee)
        front_side = "left" if left_knee < right_knee else "right"

        if not (self.FRONT_KNEE_MIN <= bent <= self.FRONT_KNEE_MAX):
            v.append("Front knee not bent correctly")
            c.append("Bend your front knee to about 90 degrees, stacked over the ankle")
            jc[(JointName.LEFT_KNEE if front_side == "left" else JointName.RIGHT_KNEE).value] = "red"
        if straight < self.BACK_LEG_STRAIGHT:
            v.append("Back leg is bent")
            c.append("Straighten and press through your back leg")

        torso = _angle_from_vertical(
            _mid(lm[JointName.LEFT_SHOULDER], lm[JointName.RIGHT_SHOULDER]),
            _mid(lm[JointName.LEFT_HIP], lm[JointName.RIGHT_HIP]),
        )
        if torso > self.MAX_TORSO_TILT:
            v.append("Torso leaning too far")
            c.append("Lift your chest and keep your torso upright")


class WarriorIPose(_LungeArmsPose):
    name = "warrior_i"
    display_name = "Warrior I"
    sanskrit = "Virabhadrasana I"
    camera_view = "front"
    target_hold_seconds = 20.0

    def evaluate(self, lm):
        v, c, jc = [], [], self._green()
        self._check_lunge(lm, v, c, jc)

        # Arms reach overhead: both wrists above the shoulders.
        ls, rs = lm[JointName.LEFT_SHOULDER], lm[JointName.RIGHT_SHOULDER]
        lw, rw = lm[JointName.LEFT_WRIST], lm[JointName.RIGHT_WRIST]
        if not (lw.y < ls.y and rw.y < rs.y):
            v.append("Arms not raised overhead")
            c.append("Reach both arms straight up alongside your ears")
            jc[JointName.LEFT_WRIST.value] = "yellow"
            jc[JointName.RIGHT_WRIST.value] = "yellow"

        return YogaEvaluation(is_in_pose=not v, violations=v, corrections=c, joint_colors=jc)


class WarriorIIPose(_LungeArmsPose):
    name = "warrior_ii"
    display_name = "Warrior II"
    sanskrit = "Virabhadrasana II"
    camera_view = "front"
    target_hold_seconds = 25.0

    ARM_LEVEL_TOLERANCE = 0.12   # wrist within this y-distance of shoulder
    MIN_ARM_SPAN = 0.45          # wrist-to-wrist horizontal spread

    def evaluate(self, lm):
        v, c, jc = [], [], self._green()
        self._check_lunge(lm, v, c, jc)

        ls, rs = lm[JointName.LEFT_SHOULDER], lm[JointName.RIGHT_SHOULDER]
        lw, rw = lm[JointName.LEFT_WRIST], lm[JointName.RIGHT_WRIST]
        arms_level = (abs(lw.y - ls.y) < self.ARM_LEVEL_TOLERANCE
                      and abs(rw.y - rs.y) < self.ARM_LEVEL_TOLERANCE)
        arms_wide = abs(lw.x - rw.x) > self.MIN_ARM_SPAN
        if not (arms_level and arms_wide):
            v.append("Arms not extended out to the sides")
            c.append("Extend both arms parallel to the floor, reaching out wide")
            jc[JointName.LEFT_WRIST.value] = "yellow"
            jc[JointName.RIGHT_WRIST.value] = "yellow"

        return YogaEvaluation(is_in_pose=not v, violations=v, corrections=c, joint_colors=jc)


class ChairPose(BaseYogaPose):
    name = "chair"
    display_name = "Chair Pose"
    sanskrit = "Utkatasana"
    camera_view = "front"
    target_hold_seconds = 20.0

    KNEE_BENT_MIN = 70.0
    KNEE_BENT_MAX = 150.0

    @property
    def required_joints(self) -> list[JointName]:
        return [
            JointName.LEFT_SHOULDER, JointName.RIGHT_SHOULDER,
            JointName.LEFT_WRIST, JointName.RIGHT_WRIST,
            JointName.LEFT_HIP, JointName.RIGHT_HIP,
            JointName.LEFT_KNEE, JointName.RIGHT_KNEE,
            JointName.LEFT_ANKLE, JointName.RIGHT_ANKLE,
        ]

    def evaluate(self, lm):
        v, c, jc = [], [], self._green()

        left_knee = _knee_angle(lm, "left")
        right_knee = _knee_angle(lm, "right")
        both_bent = (
            self.KNEE_BENT_MIN <= left_knee <= self.KNEE_BENT_MAX
            and self.KNEE_BENT_MIN <= right_knee <= self.KNEE_BENT_MAX
        )
        if not both_bent:
            v.append("Knees not bent enough")
            c.append("Bend your knees and sit your hips back as if into a chair")
            jc[JointName.LEFT_KNEE.value] = "red"
            jc[JointName.RIGHT_KNEE.value] = "red"

        ls, rs = lm[JointName.LEFT_SHOULDER], lm[JointName.RIGHT_SHOULDER]
        lw, rw = lm[JointName.LEFT_WRIST], lm[JointName.RIGHT_WRIST]
        if not (lw.y < ls.y and rw.y < rs.y):
            v.append("Arms not raised")
            c.append("Reach your arms up alongside your ears")
            jc[JointName.LEFT_WRIST.value] = "yellow"
            jc[JointName.RIGHT_WRIST.value] = "yellow"

        return YogaEvaluation(is_in_pose=not v, violations=v, corrections=c, joint_colors=jc)


class TrianglePose(BaseYogaPose):
    name = "triangle"
    display_name = "Triangle Pose"
    sanskrit = "Trikonasana"
    camera_view = "front"
    target_hold_seconds = 20.0

    LEG_STRAIGHT = 150.0
    MIN_LATERAL_TILT = 30.0      # torso bent sideways from vertical
    MIN_ARM_VERTICAL_GAP = 0.30  # one wrist high, one low

    @property
    def required_joints(self) -> list[JointName]:
        return [
            JointName.LEFT_SHOULDER, JointName.RIGHT_SHOULDER,
            JointName.LEFT_WRIST, JointName.RIGHT_WRIST,
            JointName.LEFT_HIP, JointName.RIGHT_HIP,
            JointName.LEFT_KNEE, JointName.RIGHT_KNEE,
            JointName.LEFT_ANKLE, JointName.RIGHT_ANKLE,
        ]

    def evaluate(self, lm):
        v, c, jc = [], [], self._green()

        if _knee_angle(lm, "left") < self.LEG_STRAIGHT or _knee_angle(lm, "right") < self.LEG_STRAIGHT:
            v.append("Legs are bent")
            c.append("Straighten both legs in your wide stance")
            jc[JointName.LEFT_KNEE.value] = "yellow"
            jc[JointName.RIGHT_KNEE.value] = "yellow"

        torso = _angle_from_vertical(
            _mid(lm[JointName.LEFT_SHOULDER], lm[JointName.RIGHT_SHOULDER]),
            _mid(lm[JointName.LEFT_HIP], lm[JointName.RIGHT_HIP]),
        )
        if torso < self.MIN_LATERAL_TILT:
            v.append("Not hinging sideways")
            c.append("Hinge sideways from your hip, reaching one hand down")
            jc[JointName.LEFT_SHOULDER.value] = "yellow"
            jc[JointName.RIGHT_SHOULDER.value] = "yellow"

        if abs(lm[JointName.LEFT_WRIST].y - lm[JointName.RIGHT_WRIST].y) < self.MIN_ARM_VERTICAL_GAP:
            v.append("Arms not in a vertical line")
            c.append("Stack your top arm over the bottom, forming one straight line")
            jc[JointName.LEFT_WRIST.value] = "yellow"
            jc[JointName.RIGHT_WRIST.value] = "yellow"

        return YogaEvaluation(is_in_pose=not v, violations=v, corrections=c, joint_colors=jc)


# --------------------------------------------------------------------------- #
# Floor / inverted poses (side camera)
# --------------------------------------------------------------------------- #

class DownwardDogPose(BaseYogaPose):
    name = "downward_dog"
    display_name = "Downward Dog"
    sanskrit = "Adho Mukha Svanasana"
    camera_view = "side"
    target_hold_seconds = 20.0

    HIPS_ABOVE = 0.05          # hips must be this much higher than shoulders & ankles
    ARM_STRAIGHT = 150.0
    LEG_STRAIGHT = 150.0
    PIKE_MIN = 30.0
    PIKE_MAX = 120.0

    @property
    def required_joints(self) -> list[JointName]:
        return [
            JointName.LEFT_SHOULDER, JointName.RIGHT_SHOULDER,
            JointName.LEFT_ELBOW, JointName.RIGHT_ELBOW,
            JointName.LEFT_WRIST, JointName.RIGHT_WRIST,
            JointName.LEFT_HIP, JointName.RIGHT_HIP,
            JointName.LEFT_KNEE, JointName.RIGHT_KNEE,
            JointName.LEFT_ANKLE, JointName.RIGHT_ANKLE,
        ]

    def evaluate(self, lm):
        v, c, jc = [], [], self._green()

        hip_y = _mid(lm[JointName.LEFT_HIP], lm[JointName.RIGHT_HIP])[1]
        shoulder_y = _mid(lm[JointName.LEFT_SHOULDER], lm[JointName.RIGHT_SHOULDER])[1]
        ankle_y = _mid(lm[JointName.LEFT_ANKLE], lm[JointName.RIGHT_ANKLE])[1]
        hips_highest = (hip_y < shoulder_y - self.HIPS_ABOVE) and (hip_y < ankle_y - self.HIPS_ABOVE)
        if not hips_highest:
            v.append("Hips not lifted")
            c.append("Lift your hips up and back to make an upside-down V")
            jc[JointName.LEFT_HIP.value] = "red"
            jc[JointName.RIGHT_HIP.value] = "red"

        if _elbow_angle(lm, "left") < self.ARM_STRAIGHT or _elbow_angle(lm, "right") < self.ARM_STRAIGHT:
            v.append("Arms are bent")
            c.append("Press the floor away and straighten your arms")
            jc[JointName.LEFT_ELBOW.value] = "yellow"
            jc[JointName.RIGHT_ELBOW.value] = "yellow"

        if _knee_angle(lm, "left") < self.LEG_STRAIGHT or _knee_angle(lm, "right") < self.LEG_STRAIGHT:
            v.append("Knees are bent")
            c.append("Straighten your legs, sending your heels toward the floor")
            jc[JointName.LEFT_KNEE.value] = "yellow"
            jc[JointName.RIGHT_KNEE.value] = "yellow"

        pike = (_hip_pike_angle(lm, "left") + _hip_pike_angle(lm, "right")) / 2.0
        if not (self.PIKE_MIN <= pike <= self.PIKE_MAX):
            v.append("Body angle is off")
            c.append("Form a clear peak at the hips between your arms and legs")

        return YogaEvaluation(is_in_pose=not v, violations=v, corrections=c, joint_colors=jc)


class CobraPose(BaseYogaPose):
    name = "cobra"
    display_name = "Cobra Pose"
    sanskrit = "Bhujangasana"
    camera_view = "side"
    target_hold_seconds = 15.0

    MIN_CHEST_LIFT = 0.08       # shoulders raised above hips
    MAX_BODY_TILT = 0.15        # hips and ankles roughly level (on the floor)
    FLOOR_Y = 0.55              # lower body should be in the lower image region

    @property
    def required_joints(self) -> list[JointName]:
        return [
            JointName.LEFT_SHOULDER, JointName.RIGHT_SHOULDER,
            JointName.LEFT_HIP, JointName.RIGHT_HIP,
            JointName.LEFT_KNEE, JointName.RIGHT_KNEE,
            JointName.LEFT_ANKLE, JointName.RIGHT_ANKLE,
        ]

    def evaluate(self, lm):
        v, c, jc = [], [], self._green()

        shoulder_y = _mid(lm[JointName.LEFT_SHOULDER], lm[JointName.RIGHT_SHOULDER])[1]
        hip_y = _mid(lm[JointName.LEFT_HIP], lm[JointName.RIGHT_HIP])[1]
        ankle_y = _mid(lm[JointName.LEFT_ANKLE], lm[JointName.RIGHT_ANKLE])[1]

        if not (hip_y - shoulder_y > self.MIN_CHEST_LIFT):
            v.append("Chest not lifted")
            c.append("Press through your hands and lift your chest off the floor")
            jc[JointName.LEFT_SHOULDER.value] = "red"
            jc[JointName.RIGHT_SHOULDER.value] = "red"

        lower_body_on_floor = abs(hip_y - ankle_y) < self.MAX_BODY_TILT and hip_y > self.FLOOR_Y
        if not lower_body_on_floor:
            v.append("Hips lifting off the floor")
            c.append("Keep your hips and the tops of your thighs grounded")
            jc[JointName.LEFT_HIP.value] = "yellow"
            jc[JointName.RIGHT_HIP.value] = "yellow"

        return YogaEvaluation(is_in_pose=not v, violations=v, corrections=c, joint_colors=jc)

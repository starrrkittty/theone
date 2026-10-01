"""Forearm-plank hold analysis.

The initial classifier intentionally distinguishes a stationary forearm plank
from a moving push-up. Straight-arm planks remain a future classifier case.
"""

import time

from .base import (
    BaseExercise,
    ExerciseResult,
    JointAngles,
    JointName,
    Landmark,
    calculate_angle,
)


class PlankModule(BaseExercise):
    PHASE_DISPLAY = {
        "idle": "",
        "setup": "Get into position",
        "eccentric": "",
        "concentric": "",
        "hold": "Hold steady",
    }

    HIP_DEVIATION_THRESHOLD = 0.055

    def __init__(self):
        super().__init__()
        self._hold_started_at: float | None = None
        self.hold_seconds = 0.0

    @property
    def name(self) -> str:
        return "Forearm plank"

    @property
    def required_joints(self) -> list[JointName]:
        return [
            JointName.LEFT_SHOULDER,
            JointName.RIGHT_SHOULDER,
            JointName.LEFT_ELBOW,
            JointName.RIGHT_ELBOW,
            JointName.LEFT_HIP,
            JointName.RIGHT_HIP,
            JointName.LEFT_ANKLE,
            JointName.RIGHT_ANKLE,
        ]

    def _calculate_angles(self, landmarks: dict[JointName, Landmark]) -> JointAngles:
        angles = JointAngles()
        angles.left_elbow = calculate_angle(
            landmarks[JointName.LEFT_SHOULDER],
            landmarks[JointName.LEFT_ELBOW],
            landmarks.get(JointName.LEFT_WRIST, landmarks[JointName.LEFT_ELBOW]),
        )
        angles.right_elbow = calculate_angle(
            landmarks[JointName.RIGHT_SHOULDER],
            landmarks[JointName.RIGHT_ELBOW],
            landmarks.get(JointName.RIGHT_WRIST, landmarks[JointName.RIGHT_ELBOW]),
        )
        self._last_angles = angles
        return angles

    @staticmethod
    def _body_geometry(landmarks: dict[JointName, Landmark]) -> tuple[bool, float]:
        shoulder_x = (landmarks[JointName.LEFT_SHOULDER].x + landmarks[JointName.RIGHT_SHOULDER].x) / 2
        shoulder_y = (landmarks[JointName.LEFT_SHOULDER].y + landmarks[JointName.RIGHT_SHOULDER].y) / 2
        hip_x = (landmarks[JointName.LEFT_HIP].x + landmarks[JointName.RIGHT_HIP].x) / 2
        hip_y = (landmarks[JointName.LEFT_HIP].y + landmarks[JointName.RIGHT_HIP].y) / 2
        ankle_x = (landmarks[JointName.LEFT_ANKLE].x + landmarks[JointName.RIGHT_ANKLE].x) / 2
        ankle_y = (landmarks[JointName.LEFT_ANKLE].y + landmarks[JointName.RIGHT_ANKLE].y) / 2

        horizontal = abs(shoulder_y - ankle_y) < 0.15
        dx = ankle_x - shoulder_x
        dy = ankle_y - shoulder_y
        denom = dx * dx + dy * dy
        if denom < 1e-9:
            return horizontal, 1.0
        t = ((hip_x - shoulder_x) * dx + (hip_y - shoulder_y) * dy) / denom
        projected_y = shoulder_y + t * dy
        return horizontal, hip_y - projected_y

    def detect_rep_phase(self, landmarks: dict[JointName, Landmark]) -> str:
        horizontal, _ = self._body_geometry(landmarks)
        if not horizontal:
            self._hold_started_at = None
            self.hold_seconds = 0.0
            return "idle"
        now = time.monotonic()
        if self._hold_started_at is None:
            self._hold_started_at = now
        self.hold_seconds = max(0.0, now - self._hold_started_at)
        return "hold"

    def check_form(self, landmarks: dict[JointName, Landmark]) -> ExerciseResult:
        angles = self._calculate_angles(landmarks)
        horizontal, hip_deviation = self._body_geometry(landmarks)
        violations: list[str] = []
        corrections: list[str] = []
        joint_colors = {joint.value: "green" for joint in self.required_joints}

        if not horizontal:
            violations.append("Body is not horizontal")
            corrections.append("Move into a side-on plank position with shoulders, hips, and ankles aligned")
        if hip_deviation > self.HIP_DEVIATION_THRESHOLD:
            violations.append("Hips sagging")
            corrections.append("Brace your core and lift your hips into line")
            joint_colors[JointName.LEFT_HIP.value] = "red"
            joint_colors[JointName.RIGHT_HIP.value] = "red"
        elif hip_deviation < -self.HIP_DEVIATION_THRESHOLD:
            violations.append("Hips too high")
            corrections.append("Lower your hips until your body forms a straight line")
            joint_colors[JointName.LEFT_HIP.value] = "yellow"
            joint_colors[JointName.RIGHT_HIP.value] = "yellow"

        confidence = sum(landmarks[j].visibility for j in self.required_joints) / len(self.required_joints)
        return ExerciseResult(
            is_valid=not violations,
            rep_count=0,
            rep_phase=self.current_phase,
            violations=violations,
            corrections=corrections,
            joint_colors=joint_colors,
            confidence=confidence,
            angles=angles,
            hold_seconds=self.hold_seconds,
        )

    def reset(self) -> None:
        super().reset()
        self._hold_started_at = None
        self.hold_seconds = 0.0

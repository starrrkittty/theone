"""Yoga session manager — explicit pose selection with hold timing.

Parallel to ``state_machine/manager.py`` (``FormManager``) but deliberately
**bypasses the HMM classifier**. In yoga mode the user (or a guided flow on the
frontend) explicitly picks the target pose, so there is nothing to classify —
we just check the body against the selected pose and time how long it is held.
This keeps the dynamic-exercise pipeline completely untouched.
"""

from dataclasses import dataclass, field
from typing import Optional

from config.settings import settings
from exercises.yoga_poses import BaseYogaPose
from exercises.yoga_registry import YOGA_POSE_MODULES
from pipeline.hold_timer import HoldTimer


@dataclass
class YogaFrameState:
    """Per-frame result handed to the API layer."""
    state: str                              # "idle" | "adjusting" | "holding"
    current_pose: Optional[str]
    pose_display: str = ""
    camera_view: str = "front"
    is_in_pose: bool = False
    hold_seconds: float = 0.0
    hold_target_seconds: float = 0.0
    hold_progress: float = 0.0
    hold_complete: bool = False
    just_completed: bool = False
    violations: list[str] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)
    joint_colors: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0


class YogaManager:
    """Holds one selected pose + its hold timer for a single client."""

    def __init__(self):
        self._pose: Optional[BaseYogaPose] = None
        self._pose_label: Optional[str] = None
        self._hold_timer: Optional[HoldTimer] = None
        self._frames_processed = 0

    def set_pose(self, label: str) -> bool:
        """Select (or switch to) a target pose. Returns False for unknown poses.

        Switching always starts a fresh hold so a flow transition or a manual
        pose change never carries over the previous pose's hold time.
        """
        pose_cls = YOGA_POSE_MODULES.get(label)
        if pose_cls is None:
            return False
        if label == self._pose_label and self._pose is not None:
            return True  # already on this pose — keep the running hold
        self._pose = pose_cls()
        self._pose_label = label
        self._hold_timer = HoldTimer(
            target_seconds=self._pose.target_hold_seconds,
            debounce_frames=settings.YOGA_HOLD_DEBOUNCE_FRAMES,
        )
        return True

    def process_frame(self, landmarks: list[dict]) -> YogaFrameState:
        self._frames_processed += 1

        if self._pose is None or self._hold_timer is None:
            return YogaFrameState(state="idle", current_pose=None)

        ev = self._pose.process_frame(landmarks)
        hold = self._hold_timer.update(ev.is_in_pose)

        return YogaFrameState(
            state="holding" if ev.is_in_pose else "adjusting",
            current_pose=self._pose_label,
            pose_display=self._pose.display_name,
            camera_view=self._pose.camera_view,
            is_in_pose=ev.is_in_pose,
            hold_seconds=hold["duration"],
            hold_target_seconds=self._pose.target_hold_seconds,
            hold_progress=hold["progress"],
            hold_complete=hold["complete"],
            just_completed=hold["just_completed"],
            violations=ev.violations,
            corrections=ev.corrections,
            joint_colors=ev.joint_colors,
            confidence=ev.confidence,
        )

    def reset(self) -> None:
        """Restart the current pose's hold (keeps the selected pose)."""
        if self._hold_timer is not None:
            self._hold_timer.reset()

    @property
    def current_pose(self) -> Optional[str]:
        return self._pose_label

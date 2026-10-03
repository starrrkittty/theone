"""Canonical supported yoga-pose metadata.

Parallels ``exercises/registry.py`` (which covers the dynamic, rep-counted
exercises) but is kept separate so the classifier-driven exercise pipeline and
the explicit-selection yoga pipeline don't drift into each other.
"""

from dataclasses import dataclass
from typing import Type

from .yoga_poses import (
    BaseYogaPose,
    ChairPose,
    CobraPose,
    DownwardDogPose,
    MountainPose,
    TreePose,
    TrianglePose,
    WarriorIPose,
    WarriorIIPose,
)


@dataclass(frozen=True)
class YogaPoseDefinition:
    label: str
    display_name: str
    sanskrit: str
    camera_view: str          # 'front' | 'side'
    target_hold_seconds: float


# Module map drives both the registry payload and YogaManager instantiation.
YOGA_POSE_MODULES: dict[str, Type[BaseYogaPose]] = {
    MountainPose.name: MountainPose,
    TreePose.name: TreePose,
    WarriorIPose.name: WarriorIPose,
    WarriorIIPose.name: WarriorIIPose,
    ChairPose.name: ChairPose,
    TrianglePose.name: TrianglePose,
    DownwardDogPose.name: DownwardDogPose,
    CobraPose.name: CobraPose,
}


SUPPORTED_YOGA_POSES: tuple[YogaPoseDefinition, ...] = tuple(
    YogaPoseDefinition(
        label=cls.name,
        display_name=cls.display_name,
        sanskrit=cls.sanskrit,
        camera_view=cls.camera_view,
        target_hold_seconds=cls.target_hold_seconds,
    )
    for cls in YOGA_POSE_MODULES.values()
)

SUPPORTED_YOGA_LABELS = frozenset(YOGA_POSE_MODULES.keys())


def supported_yoga_payload() -> list[dict]:
    """JSON-serializable pose list for the /yoga/poses + health endpoints."""
    return [
        {
            "label": d.label,
            "display_name": d.display_name,
            "sanskrit": d.sanskrit,
            "camera_view": d.camera_view,
            "target_hold_seconds": d.target_hold_seconds,
        }
        for d in SUPPORTED_YOGA_POSES
    ]

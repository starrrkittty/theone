"""URDF-backed kinematic metadata used by deterministic pose analysis."""

from .urdf_loader import HumanKinematicModel, JointLimit, JointSpec, load_urdf

__all__ = ["HumanKinematicModel", "JointLimit", "JointSpec", "load_urdf"]

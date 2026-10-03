"""Small, dependency-free URDF metadata loader.

V1 only needs the joint tree, axes, origins, and limits. Forward/inverse
dynamics are deliberately out of scope; a robotics library can be added later
without changing the ActionReport contract.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET
import math
try:
    from urdf_parser_py.urdf import URDF
except ImportError:
    URDF = None


def parser_backend():
    return "urdf-parser-py/0.0.4+strict_validation" if URDF else "validated_elementtree"


class UrdfError(ValueError):
    """Raised when required URDF structure is missing or inconsistent."""


@dataclass(frozen=True)
class JointLimit:
    lower: Optional[float] = None
    upper: Optional[float] = None
    effort: Optional[float] = None
    velocity: Optional[float] = None


@dataclass(frozen=True)
class JointSpec:
    name: str
    joint_type: str
    parent: str
    child: str
    axis: tuple[float, float, float] = (1.0, 0.0, 0.0)
    origin_xyz: tuple[float, float, float] = (0.0, 0.0, 0.0)
    origin_rpy: tuple[float, float, float] = (0.0, 0.0, 0.0)
    limit: JointLimit = field(default_factory=JointLimit)


@dataclass(frozen=True)
class HumanKinematicModel:
    name: str
    links: frozenset[str]
    joints: dict[str, JointSpec]

    def parent_joint_of(self, child_link: str) -> Optional[JointSpec]:
        for joint in self.joints.values():
            if joint.child == child_link:
                return joint
        return None

    def validate_mapping(self, landmark_to_joint: dict[str, str]) -> list[str]:
        """Return mapping errors instead of silently accepting bad names."""
        return [
            f"{landmark}: unknown URDF joint '{joint}'"
            for landmark, joint in landmark_to_joint.items()
            if joint not in self.joints
        ]

    def compact_joint_map(self) -> dict[str, dict]:
        """Compact JSON-ready representation safe to pass to other modules."""
        return {
            name: {
                "parent": joint.parent,
                "child": joint.child,
                "type": joint.joint_type,
                "axis": list(joint.axis),
                "lower": joint.limit.lower,
                "upper": joint.limit.upper,
                "origin_xyz": list(joint.origin_xyz),
                "origin_rpy": list(joint.origin_rpy),
            }
            for name, joint in self.joints.items()
        }


def load_urdf(path: str | Path) -> HumanKinematicModel:
    source = Path(path)
    if not source.is_file():
        raise UrdfError(f"URDF file not found: {source}")
    try:
        root = ET.parse(source).getroot()
    except ET.ParseError as exc:
        raise UrdfError(f"Invalid URDF XML: {exc}") from exc

    if root.tag != "robot":
        raise UrdfError("URDF root element must be <robot>")
    return parse_urdf(ET.tostring(root, encoding="unicode"))


def parse_urdf(xml: str) -> HumanKinematicModel:
    if len(xml) > 250_000 or "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
        raise UrdfError("URDF must be bounded XML without declarations/entities")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise UrdfError(f"Invalid URDF XML: {exc}") from exc
    if root.tag != "robot":
        raise UrdfError("URDF root element must be <robot>")
    robot_name = root.attrib.get("name", "human")
    links = frozenset(
        element.attrib["name"]
        for element in root.findall("link")
        if element.attrib.get("name")
    )
    if not links:
        raise UrdfError("URDF must define at least one link")

    joints: dict[str, JointSpec] = {}
    children: set[str] = set()
    for element in root.findall("joint"):
        name = element.attrib.get("name")
        joint_type = element.attrib.get("type")
        parent_el = element.find("parent")
        child_el = element.find("child")
        if not name or not joint_type or parent_el is None or child_el is None:
            raise UrdfError("Every joint requires name, type, parent, and child")
        parent = parent_el.attrib.get("link", "")
        child = child_el.attrib.get("link", "")
        if parent not in links or child not in links:
            raise UrdfError(f"Joint '{name}' references an unknown link")
        if child in children:
            raise UrdfError(f"Link '{child}' has more than one parent joint")
        if name in joints:
            raise UrdfError(f"Duplicate joint name: {name}")

        origin = element.find("origin")
        axis = element.find("axis")
        limit = element.find("limit")
        joints[name] = JointSpec(
            name=name,
            joint_type=joint_type,
            parent=parent,
            child=child,
            axis=_vector(axis.attrib.get("xyz") if axis is not None else None, (1.0, 0.0, 0.0)),
            origin_xyz=_vector(origin.attrib.get("xyz") if origin is not None else None),
            origin_rpy=_vector(origin.attrib.get("rpy") if origin is not None else None),
            limit=JointLimit(
                lower=_number(limit.attrib.get("lower")) if limit is not None else None,
                upper=_number(limit.attrib.get("upper")) if limit is not None else None,
                effort=_number(limit.attrib.get("effort")) if limit is not None else None,
                velocity=_number(limit.attrib.get("velocity")) if limit is not None else None,
            ),
        )
        children.add(child)

    if len(links) != len(root.findall("link")):
        raise UrdfError("Link names must be present and unique")
    roots = links - children
    if len(roots) != 1:
        raise UrdfError("URDF must have exactly one root link")
    reachable = set(roots)
    pending = list(joints.values())
    while pending:
        available = [joint for joint in pending if joint.parent in reachable]
        if not available:
            raise UrdfError("URDF has a cycle or disconnected links")
        for joint in available:
            if joint.child in reachable:
                raise UrdfError("URDF contains a cycle")
            if joint.joint_type not in {"fixed", "revolute", "continuous", "prismatic"}:
                raise UrdfError("Unsupported joint type")
            if joint.joint_type != "fixed" and sum(v*v for v in joint.axis) < 1e-12:
                raise UrdfError("Movable joint axis cannot be zero")
            if joint.limit.lower is not None and joint.limit.upper is not None and joint.limit.lower > joint.limit.upper:
                raise UrdfError("Reversed joint limits")
            reachable.add(joint.child)
            pending.remove(joint)
    if reachable != set(links):
        raise UrdfError("Disconnected links")
    if URDF is not None:
        try:
            parsed = URDF.from_xml_string(xml)
            if set(parsed.joint_map) != set(joints) or set(parsed.link_map) != set(links):
                raise UrdfError("Parser topology mismatch")
            # Use the library's parsed structure after our stricter validation.
            joints = {name: JointSpec(name=name, joint_type=j.joint_type, parent=j.parent, child=j.child,
                       axis=tuple(j.axis or (1, 0, 0)),
                       origin_xyz=tuple(j.origin.xyz or (0, 0, 0)) if j.origin else (0, 0, 0),
                       origin_rpy=tuple(j.origin.rpy or (0, 0, 0)) if j.origin else (0, 0, 0),
                       limit=JointLimit(lower=j.limit.lower, upper=j.limit.upper, effort=j.limit.effort,
                                        velocity=j.limit.velocity) if j.limit else JointLimit())
                      for name, j in parsed.joint_map.items()}
        except (ValueError, AssertionError, TypeError, AttributeError) as exc:
            raise UrdfError("urdf-parser-py rejected model") from exc
    return HumanKinematicModel(robot_name, links, joints)


def _vector(
    value: Optional[str],
    default: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> tuple[float, float, float]:
    if not value:
        return default
    parts = value.split()
    if len(parts) != 3:
        raise UrdfError(f"Expected a three-value vector, got: {value}")
    try:
        values = tuple(float(part) for part in parts)
        if not all(math.isfinite(v) for v in values):
            raise ValueError()
        return values
    except ValueError as exc:
        raise UrdfError(f"Invalid vector: {value}") from exc


def _number(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        result = float(value)
        if not math.isfinite(result):
            raise ValueError()
        return result
    except ValueError as exc:
        raise UrdfError(f"Invalid number: {value}") from exc

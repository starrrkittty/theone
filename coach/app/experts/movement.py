from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Rule:
    code: str
    joint: str
    predicate: Any
    expected: str
    cue: str
    source_id: str = "prototype_review_heuristic"


class MovementSpecialist:
    def __init__(self, specialist_id: str, exercises: tuple[str, ...], rules: tuple[Rule, ...], description: str, required_observations: tuple[str, ...], guidance_level: str = "specialized"):
        self.specialist_id = specialist_id
        self.supported_exercises = frozenset(exercises)
        self.rules = rules
        self.description = description
        self.required_observations = required_observations
        self.guidance_level = guidance_level

    def analyze(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        joints = data["joints"]
        findings = []
        for rule in self.rules:
            observation = joints.get(rule.joint)
            if observation is None:
                continue
            confidence = observation.get("confidence", 1.0)
            if confidence < 0.55:
                continue
            value = observation["angle_deg"]
            if rule.predicate(value, data):
                findings.append({
                    "code": rule.code, "severity": "caution", "joint": rule.joint,
                    "observed": value, "expected": rule.expected,
                    "confidence": confidence, "source_ids": [rule.source_id],
                    "cue": rule.cue,
                })
        return findings


def _gt(phase: str, threshold: float):
    return lambda value, data: (data["phase"] in (phase, "unknown") and value > threshold)


def _lt(phase: str, threshold: float):
    return lambda value, data: (data["phase"] in (phase, "unknown") and value < threshold)


SPECIALISTS = [
    MovementSpecialist("curl_form", ("bicep_curl", "alternate_bicep_curl"), (), "Elbow flexion/extension and alternating-arm phases; no shoulder diagnosis.", ("left_elbow_flexion", "right_elbow_flexion", "trunk_inclination")),
    MovementSpecialist("squat_form", ("bodyweight_squat", "goblet_squat", "back_squat", "front_squat", "sit_to_stand"), (
        Rule("squat_trunk_inclination_observed", "trunk_inclination", _gt("bottom", 55), "Keep your torso position controlled and within a range you can maintain.", "Try a slightly shallower comfortable squat and keep the trunk position controlled."),
        Rule("squat_knee_alignment_proxy", "knee_medial_deviation_deg", _gt("bottom", 12), "A 2D medial-deviation estimate is only a camera-dependent proxy; aim for a comfortable, controlled knee path.", "Reduce range or load and use a controlled knee path; check camera alignment before treating this as a form finding."),
    ), "Squat depth and knee/trunk observations; explicitly avoids prescribing one required depth.", ("trunk_inclination", "knee_flexion", "left_knee_flexion", "right_knee_flexion", "knee_medial_deviation_deg")),
    MovementSpecialist("hinge_form", ("hip_hinge", "hip_hinge_practice", "deadlift", "romanian_deadlift", "kettlebell_swing"), (
        Rule("hinge_trunk_inclination_observed", "trunk_inclination", _gt("unknown", 70), "A large trunk angle alone does not establish poor technique; control and load context are required.", "Reduce the range or load until the hinge feels controlled; side-view angle alone cannot assess spinal loading."),
        Rule("hinge_knee_bend_proxy", "knee_flexion", _gt("unknown", 115), "Knee bend varies by hinge variation and individual strategy.", "Review the intended exercise variation and use a comfortable, repeatable setup."),
    ), "Hip-dominant patterns; warns that angles alone cannot assess spinal position or bar path.", ("trunk_inclination", "knee_flexion", "left_knee_flexion", "right_knee_flexion", "hip_flexion", "left_hip_flexion", "right_hip_flexion")),
    MovementSpecialist("push_form", ("push_up", "overhead_press", "bench_press", "incline_push_up", "wall_push_up", "bent_knee_push_up"), (
        Rule("push_elbow_range_observed", "elbow_flexion", _lt("bottom", 35), "Use a pain-free, controllable range that matches the exercise variation.", "Shorten the range and keep the repetition controlled if the bottom position is uncomfortable."),
        Rule("push_trunk_alignment_proxy", "trunk_inclination", _gt("hold", 25), "A trunk angle from one camera view is not enough to determine whole-body alignment.", "Reposition the camera and keep the trunk controlled; stop if you feel pain."),
    ), "Horizontal and vertical pushing; no claims about shoulder safety from a single joint angle.", ("elbow_flexion", "left_elbow_flexion", "right_elbow_flexion", "trunk_inclination", "shoulder_flexion")),
    MovementSpecialist("pull_form", ("resistance_band_row", "supported_row_variation", "single_arm_band_row", "barbell_bent_over_row"), (
        Rule("row_shrug_proxy", "shoulder_elevation_deg", _gt("unknown", 35), "A shoulder-elevation estimate is camera-dependent and does not establish injury risk.", "Use a lighter resistance and keep the shoulder motion comfortable and controlled."),
    ), "Horizontal pulling; requires a reliable shoulder-elevation observation before offering a cue.", ("elbow_flexion", "shoulder_elevation_deg")),
    MovementSpecialist("lunge_form", ("forward_lunge", "reverse_lunge", "split_squat", "anti_rotation_reverse_lunge"), (
        Rule("lunge_trunk_control_observed", "trunk_inclination", _gt("bottom", 55), "Trunk strategy varies; prioritize balance and a controlled, comfortable range.", "Use support or reduce range until the repetition feels balanced and controlled."),
        Rule("lunge_knee_path_proxy", "knee_medial_deviation_deg", _gt("bottom", 12), "This camera-dependent 2D estimate is not a diagnosis or universal alignment limit.", "Check the front camera view and use a controlled knee path; reduce range if uncomfortable."),
    ), "Single-leg patterns; knee path is treated as a low-certainty 2D proxy.", ("trunk_inclination", "knee_medial_deviation_deg", "left_knee_flexion", "right_knee_flexion")),
    MovementSpecialist("plank_form", ("plank", "side_plank", "short_plank", "dead_bug", "forearm_plank"), (
        Rule("plank_trunk_alignment_proxy", "trunk_sag_angle", _gt("hold", 15), "A pose estimate can be affected by camera placement and landmark confidence.", "Shorten the hold, reset, and use a position you can maintain without pain."),
    ), "Static trunk holds; duration and discomfort should be supplied separately.", ("trunk_sag_angle", "hold_duration_seconds")),
    MovementSpecialist("balance_form", ("single_leg_stance", "single_leg_balance"), (
        Rule("balance_trunk_sway_proxy", "trunk_sway_deg", _gt("hold", 12), "Single-view sway is an approximate stability proxy, not a diagnosis.", "Stand near stable support and use an easier balance variation."),
    ), "Balance support and stability proxies; recommend a safe environment.", ("trunk_sway_deg", "support_used")),
    MovementSpecialist("lower_body_general", ("lunge",), (), "Semantic lower-body movement guidance; no verified lunge form assessment.", (), "general"),
    MovementSpecialist("upper_body_push_general", ("shoulder_press", "lateral_raise"), (), "Distinguish pressing from raising without inferring shoulder form from a class label.", (), "general"),
    MovementSpecialist("upper_body_pull_general", ("dumbbell_row", "pullup"), (), "General pulling guidance; equipment and grip are not verified by pose classification.", (), "general"),
    MovementSpecialist("arms_general", ("tricep_extension",), (), "General arm-exercise guidance without an elbow-angle standard.", (), "general"),
    MovementSpecialist("core_general", ("situp",), (), "General trunk-exercise guidance without a verified repetition or spinal-form assessment.", (), "general"),
    MovementSpecialist("cardio_general", ("jumping_jack", "jump_rope", "running_in_place"), (), "General rhythmic-activity guidance; pose-only recognition does not observe a rope.", (), "general"),
    MovementSpecialist("yoga_general", ("yoga_tree", "yoga_triangle"), (), "General pose-family guidance; hold quality and balance require separate observations.", (), "general"),
    MovementSpecialist("full_body_general", ("burpee",), (), "General multi-phase exercise guidance without verified phase-level correction.", (), "general"),
]

BY_EXERCISE = {exercise: agent for agent in SPECIALISTS for exercise in agent.supported_exercises}


def catalog() -> list[dict[str, Any]]:
    return [{"specialist_id": agent.specialist_id, "supported_exercises": sorted(agent.supported_exercises), "description": agent.description, "required_observations": list(agent.required_observations), "guidance_level": agent.guidance_level} for agent in SPECIALISTS]

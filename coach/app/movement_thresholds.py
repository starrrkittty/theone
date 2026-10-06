"""Scoped prototype targets for the first ten movement patterns."""

from copy import deepcopy


_SHARED_SQUAT_DETECTION = {
    "status": "implemented_for_bodyweight_squat_only",
    "bottom_angle_max_deg": 126,
    "top_angle_min_deg": 134,
    "angle": "included knee segment angle",
}
_SHARED_PUSH_DETECTION = {
    "status": "implemented_by_generic_pushup_module; variation_not_classified",
    "bottom_angle_max_deg": 126,
    "top_angle_min_deg": 134,
    "angle": "included elbow segment angle",
}

THRESHOLD_PROFILES = {
    "bodyweight_squat": {
        "specialist_id": "squat_form",
        "a_readiness": "core_realtime",
        "camera_view": "side_for_knee_depth; front_for_knee_path",
        "status": "provisional_numeric_proxy",
        "evaluation": [{
            "metrics": ["left_knee_flexion", "right_knee_flexion"],
            "aggregation": "mean_of_reliable_sides",
            "phase_any_of": ["descent", "bottom", "hold"],
            "definition": "included_segment_angle", "operator": "<=",
            "value_deg": 100, "confidence_min": 0.55,
            "source_ids": ["ace_squat"],
            "basis": "Project proxy around the coaching cue to descend toward thigh-parallel depth; the source does not prescribe this angle.",
        }],
        "detection": _SHARED_SQUAT_DETECTION,
    },
    "goblet_squat": {
        "specialist_id": "squat_form", "a_readiness": "semantic_only",
        "camera_view": "side_for_depth; front_for_knee_path",
        "status": "qualitative_only",
        "evaluation": [], "detection": {"status": "not_available"},
        "cue": "Use a comfortable, controlled depth with stable foot contact and a repeatable knee path; do not inherit the bodyweight-squat angle target without coach review.",
        "source_ids": ["ace_squat"],
    },
    "sit_to_stand": {
        "specialist_id": "squat_form", "a_readiness": "not_in_a_realtime_set",
        "camera_view": "side",
        "status": "requires_seat_and_user_context",
        "evaluation": [], "detection": {"status": "not_available"},
        "cue": "Seat height and the user's capacity change the required joint range; assess controlled stand/sit transitions rather than a universal knee angle.",
        "source_ids": ["nhs_strength"],
    },
    "push_up": {
        "specialist_id": "push_form", "a_readiness": "core_realtime_pushup_module",
        "camera_view": "side_for_elbow_range; side_or_oblique_for_trunk_shape",
        "status": "provisional_numeric_proxy",
        "source_review_status": "needs_standard_pushup_source",
        "evaluation": [{
            "metrics": ["left_elbow_flexion", "right_elbow_flexion"],
            "aggregation": "mean_of_reliable_sides",
            "phase_any_of": ["descent", "bottom", "hold"],
            "definition": "included_segment_angle", "operator": "<=",
            "value_deg": 100, "confidence_min": 0.55,
            "source_ids": [],
            "basis": "Project camera proxy for a controlled lower position; no standard-push-up source in the current reviewed knowledge set prescribes this angle.",
        }],
        "detection": _SHARED_PUSH_DETECTION,
    },
    "bent_knee_push_up": {
        "specialist_id": "push_form", "a_readiness": "generic_pushup_module_does_not_identify_regression",
        "camera_view": "side_or_oblique",
        "status": "qualitative_only",
        "evaluation": [], "detection": {"status": "shared_generic_pushup_cycle_only"},
        "cue": "Use a controlled, comfortable range and maintain trunk control; the ACE page is specific to this regression and gives no universal elbow-angle target.",
        "source_ids": ["ace_knee_pushup"],
    },
    "forearm_plank": {
        "specialist_id": "plank_form", "a_readiness": "core_realtime_hold",
        "camera_view": "side",
        "status": "provisional_numeric_proxy",
        "evaluation": [{
            "metric": "trunk_sag_angle", "phase": "hold",
            "definition": "projected_deviation", "operator": "<=",
            "value_deg": 10, "confidence_min": 0.55,
            "source_ids": ["ace_front_plank"],
            "basis": "Project tolerance for the qualitative cue to maintain a controlled trunk line; the source gives no angle cutoff.",
        }],
        "detection": {"status": "hold_timer; no repetition", "candidate_alert_gt_deg": 15},
    },
    "bicep_curl": {
        "specialist_id": "curl_form", "a_readiness": "core_realtime",
        "camera_view": "side_or_oblique_for_active_arm",
        "status": "provisional_numeric_proxy",
        "source_review_status": "project_heuristic_only",
        "evaluation": [{
            "metrics": ["left_elbow_flexion", "right_elbow_flexion"],
            "aggregation": "evaluate_reliable_arms_independently",
            "phase_any_of": ["ascent", "hold"],
            "definition": "included_segment_angle", "operator": "<=",
            "value_deg": 80, "confidence_min": 0.55,
            "source_ids": ["prototype_review_heuristic"],
            "basis": "Existing project contraction cue, not a research-derived universal target.",
        }],
        "detection": {"status": "implemented", "bottom_angle_max_deg": 108, "top_angle_min_deg": 122},
    },
    "alternate_bicep_curl": {
        "specialist_id": "curl_form", "a_readiness": "core_realtime",
        "camera_view": "front_or_oblique_for_both_arms",
        "status": "requires_active_side_metadata",
        "evaluation": [],
        "detection": {"status": "implemented_per_arm", "bottom_angle_max_deg": 108, "top_angle_min_deg": 122},
        "cue": "Apply the curl target only after A identifies the active arm for this phase; compare sides only at matching phases.",
    },
    "reverse_lunge": {
        "specialist_id": "lunge_form", "a_readiness": "semantic_only",
        "camera_view": "front_for_projected_knee_path; side_for_sagittal_range",
        "status": "observation_only_no_universal_angle_target",
        "evaluation": [], "detection": {"status": "not_available"},
        "cue": "Confirm support side and phase before comparing limbs. The existing 12 deg projected knee-deviation trigger is an unvalidated camera heuristic, not a pass/fail or safety threshold.",
        "source_ids": ["ace_reverse_lunge"],
    },
    "barbell_bent_over_row": {
        "specialist_id": "pull_form", "a_readiness": "semantic_only",
        "camera_view": "side_for_trunk; front_for_shoulder_elevation",
        "status": "observation_only_no_universal_angle_target",
        "evaluation": [], "detection": {"status": "not_available"},
        "cue": "Describe shoulder elevation only when directly measured. The existing 35 deg trigger is an unvalidated project heuristic, not a universal rowing-form limit.",
        "source_ids": ["ace_bent_row"],
    },
}


def threshold_profile(exercise_id: str) -> dict | None:
    """Return a detached profile so request handling cannot mutate shared data."""
    profile = THRESHOLD_PROFILES.get(exercise_id)
    return deepcopy(profile) if profile is not None else None

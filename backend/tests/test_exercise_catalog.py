from exercises.catalog import get_exercise_profile, semantic_profile
from recognition.routing import route_exercise


def test_aliases_resolve_to_canonical_exercise():
    assert get_exercise_profile("俯卧撑").id == "pushup"
    assert get_exercise_profile("push-up").id == "pushup"
    assert get_exercise_profile("保加利亚蹲").id == "bulgarian_split_squat"


def test_verified_action_routes_to_precise_specialist():
    decision = route_exercise("squat")
    assert decision.mode == "verified_specialist"
    assert decision.specialist == "squat_specialist"
    assert decision.profile.precise_rep_count is True
    assert decision.profile.specialized_form_correction is True


def test_semantic_only_action_routes_to_category_generalist():
    decision = route_exercise("bulgarian_split_squat")
    assert decision.mode == "general_coaching"
    assert decision.specialist == "lower_body_general"
    assert decision.profile.precise_rep_count is False


def test_safe_dynamic_semantic_label_never_gains_precise_capabilities():
    profile = semantic_profile(
        "single_arm_cable_press",
        display_name="单臂绳索推举",
        category="upper_body_push",
    )
    assert profile is not None
    assert profile.specialist is None
    assert profile.fallback_specialist == "upper_body_push_general"
    assert profile.specialized_form_correction is False


def test_untrusted_semantic_label_is_rejected():
    assert semantic_profile("../../bad label", category="core") is None


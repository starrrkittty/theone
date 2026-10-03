"""Canonical exercise ontology shared by recognition, routing, and clients.

The small realtime classifier only covers a verified core set.  This catalog is
deliberately broader: a semantic video recognizer may identify any entry here,
while capability flags prevent the product from pretending that every known
exercise already has precise counting and form correction.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Optional


GENERAL_SPECIALISTS = {
    "lower_body": "lower_body_general",
    "upper_body_push": "upper_body_push_general",
    "upper_body_pull": "upper_body_pull_general",
    "arms": "arms_general",
    "core": "core_general",
    "cardio": "cardio_general",
    "mobility": "mobility_general",
    "yoga": "yoga_general",
    "full_body": "full_body_general",
    "other": "full_body_general",
}


@dataclass(frozen=True)
class ExerciseProfile:
    id: str
    display_name_zh: str
    display_name_en: str
    category: str
    aliases: tuple[str, ...] = ()
    specialist: Optional[str] = None
    fallback_specialist: str = "full_body_general"
    precise_rep_count: bool = False
    specialized_form_correction: bool = False
    hold_timing: bool = False
    camera_views: tuple[str, ...] = ("front", "side")

    @property
    def recognition_level(self) -> str:
        return "verified_specialist" if self.specialist else "semantic_only"

    def to_payload(self) -> dict:
        payload = asdict(self)
        payload["recognition_level"] = self.recognition_level
        return payload


def _p(
    id: str,
    zh: str,
    en: str,
    category: str,
    *aliases: str,
    specialist: Optional[str] = None,
    count: bool = False,
    form: bool = False,
    hold: bool = False,
    views: tuple[str, ...] = ("front", "side"),
) -> ExerciseProfile:
    return ExerciseProfile(
        id=id,
        display_name_zh=zh,
        display_name_en=en,
        category=category,
        aliases=aliases,
        specialist=specialist,
        fallback_specialist=GENERAL_SPECIALISTS.get(category, "full_body_general"),
        precise_rep_count=count,
        specialized_form_correction=form,
        hold_timing=hold,
        camera_views=views,
    )


# The first five entries are the currently verified realtime specialist set.
# Remaining entries form a practical common-exercise vocabulary for semantic
# recognition and safe routing to a category-level coach.
EXERCISE_CATALOG: tuple[ExerciseProfile, ...] = (
    _p("squat", "深蹲", "Squat", "lower_body", "徒手深蹲", "air squat", "bodyweight squat",
       specialist="squat_specialist", count=True, form=True),
    _p("pushup", "俯卧撑", "Push-up", "upper_body_push", "push up", "push-up",
       specialist="pushup_specialist", count=True, form=True),
    _p("plank", "前臂平板支撑", "Forearm Plank", "core", "平板支撑", "forearm plank",
       specialist="plank_specialist", form=True, hold=True, views=("side",)),
    _p("bicep_curl", "哑铃弯举", "Bicep Curl", "arms", "二头弯举", "dumbbell curl", "biceps curl",
       specialist="bicep_curl_specialist", count=True, form=True),
    _p("alternate_bicep_curl", "交替哑铃弯举", "Alternate Bicep Curl", "arms", "交替弯举", "alternating curl",
       specialist="alternate_bicep_curl_specialist", count=True, form=True),
    _p("lunge", "弓步蹲", "Lunge", "lower_body", "弓箭步", "forward lunge"),
    _p("reverse_lunge", "反向弓步蹲", "Reverse Lunge", "lower_body", "后撤弓步"),
    _p("bulgarian_split_squat", "保加利亚分腿蹲", "Bulgarian Split Squat", "lower_body", "保加利亚蹲", "后脚抬高分腿蹲"),
    _p("goblet_squat", "高脚杯深蹲", "Goblet Squat", "lower_body", "壶铃深蹲"),
    _p("sumo_squat", "相扑深蹲", "Sumo Squat", "lower_body", "宽距深蹲"),
    _p("deadlift", "硬拉", "Deadlift", "lower_body", "barbell deadlift"),
    _p("romanian_deadlift", "罗马尼亚硬拉", "Romanian Deadlift", "lower_body", "rdl"),
    _p("hip_thrust", "臀推", "Hip Thrust", "lower_body", "杠铃臀推"),
    _p("glute_bridge", "臀桥", "Glute Bridge", "lower_body", "bridge"),
    _p("calf_raise", "提踵", "Calf Raise", "lower_body", "standing calf raise"),
    _p("step_up", "登阶", "Step-up", "lower_body", "台阶训练"),
    _p("bench_press", "卧推", "Bench Press", "upper_body_push", "杠铃卧推"),
    _p("dumbbell_bench_press", "哑铃卧推", "Dumbbell Bench Press", "upper_body_push"),
    _p("shoulder_press", "肩推", "Shoulder Press", "upper_body_push", "推肩", "overhead press"),
    _p("lateral_raise", "侧平举", "Lateral Raise", "upper_body_push", "哑铃侧平举"),
    _p("front_raise", "前平举", "Front Raise", "upper_body_push", "哑铃前平举"),
    _p("tricep_extension", "肱三头肌伸展", "Tricep Extension", "arms", "臂屈伸", "triceps extension"),
    _p("dip", "双杠臂屈伸", "Dip", "upper_body_push", "dips"),
    _p("pullup", "引体向上", "Pull-up", "upper_body_pull", "pull up", "pull-up"),
    _p("chinup", "反手引体向上", "Chin-up", "upper_body_pull", "chin up"),
    _p("dumbbell_row", "哑铃划船", "Dumbbell Row", "upper_body_pull", "单臂哑铃划船"),
    _p("barbell_row", "杠铃划船", "Barbell Row", "upper_body_pull", "俯身杠铃划船"),
    _p("lat_pulldown", "高位下拉", "Lat Pulldown", "upper_body_pull", "背阔肌下拉"),
    _p("situp", "仰卧起坐", "Sit-up", "core", "sit up"),
    _p("crunch", "卷腹", "Crunch", "core", "腹部卷曲"),
    _p("russian_twist", "俄罗斯转体", "Russian Twist", "core"),
    _p("leg_raise", "仰卧举腿", "Leg Raise", "core", "lying leg raise"),
    _p("mountain_climber", "登山跑", "Mountain Climber", "cardio", "登山者"),
    _p("jumping_jack", "开合跳", "Jumping Jack", "cardio", "jumping jacks"),
    _p("burpee", "波比跳", "Burpee", "full_body", "burpees"),
    _p("high_knees", "高抬腿", "High Knees", "cardio", "原地高抬腿"),
    _p("jump_rope", "跳绳", "Jump Rope", "cardio", "skipping rope"),
    _p("running", "跑步", "Running", "cardio", "慢跑", "jogging"),
    _p("cycling", "骑行", "Cycling", "cardio", "动感单车"),
    _p("kettlebell_swing", "壶铃摆动", "Kettlebell Swing", "full_body", "壶铃摇摆"),
    _p("battle_rope", "战绳", "Battle Rope", "full_body", "battle ropes"),
)


_BY_ID = {profile.id: profile for profile in EXERCISE_CATALOG}


def _normalize_key(value: str) -> str:
    value = value.strip().lower().replace("-", "_")
    value = re.sub(r"[\s/]+", "_", value)
    return re.sub(r"_+", "_", value).strip("_")


_BY_ALIAS: dict[str, ExerciseProfile] = {}
for _profile in EXERCISE_CATALOG:
    for _alias in (_profile.id, _profile.display_name_zh, _profile.display_name_en, *_profile.aliases):
        _BY_ALIAS[_normalize_key(_alias)] = _profile


def get_exercise_profile(value: str) -> Optional[ExerciseProfile]:
    """Resolve a canonical id or common Chinese/English alias."""
    if not isinstance(value, str) or not value.strip():
        return None
    return _BY_ALIAS.get(_normalize_key(value))


def semantic_profile(
    exercise_id: str,
    *,
    display_name: Optional[str] = None,
    category: str = "other",
) -> Optional[ExerciseProfile]:
    """Return a known profile or a constrained semantic-only fallback.

    Unknown labels from a video model remain usable for category-level routing,
    but never gain precise counting/form capabilities by implication.
    """
    known = get_exercise_profile(exercise_id)
    if known:
        return known
    canonical = _normalize_key(exercise_id)
    if not re.fullmatch(r"[a-z0-9_]{2,64}", canonical):
        return None
    normalized_category = _normalize_key(category)
    if normalized_category not in GENERAL_SPECIALISTS:
        normalized_category = "other"
    return ExerciseProfile(
        id=canonical,
        display_name_zh=(display_name or canonical).strip()[:80],
        display_name_en=canonical.replace("_", " ").title(),
        category=normalized_category,
        fallback_specialist=GENERAL_SPECIALISTS[normalized_category],
    )


def exercise_catalog_payload() -> list[dict]:
    return [profile.to_payload() for profile in EXERCISE_CATALOG]


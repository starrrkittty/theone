"""Describe what a pose measurement supports without inventing form thresholds."""
from app.engine import InputError
from app.experts.movement import BY_EXERCISE

CONFIDENCE_FLOOR = 0.55  # Project data-quality gate, not a scientific form threshold.
DEFINITIONS = {"flexion_from_extension", "included_segment_angle", "inclination_from_vertical", "inclination_from_horizontal", "projected_deviation"}
FLEXION = {"knee_flexion", "hip_flexion", "elbow_flexion", "shoulder_flexion", "left_knee_flexion", "right_knee_flexion"}
FLEXION |= {"left_elbow_flexion", "right_elbow_flexion", "left_hip_flexion", "right_hip_flexion"}
FRONTAL = {"knee_medial_deviation_deg", "shoulder_elevation_deg"}
SAGITTAL = FLEXION | {"trunk_inclination", "trunk_sag_angle"}
CHECKLISTS = {
    "curl_form": ["区分同时与交替弯举；交替动作不能要求两侧角度同步。", "观察肘活动，肩骨段夹角不等于肩屈曲。", "躯干晃动、动作节奏及疲劳需要可靠时间序列。"],
    "squat_form": ["区分自重、前蹲、后蹲与坐站变式。", "分别观察下降、底部和上升；不要要求所有人同一蹲深。", "膝前移、膝内移和膝屈曲是不同指标。", "脚跟接触、左右对称、躯干形状需要对应观测；躯干倾角不等于脊柱弯曲。"],
    "hinge_form": ["区分硬拉、罗马尼亚硬拉和摆动的运动目标。", "结合髋膝屈曲及负重；躯干倾角不等于腰椎屈曲。", "杠铃路径、速度和疲劳必须有轨迹或时间序列。"],
    "push_form": ["区分俯卧撑与卧推、推举。", "肘屈曲和上臂外展角不同；不强制通用 45° 肘角。", "身体排列需要肩髋踝或躯干形状观测；不从单个倾角确认身体直线。"],
    "pull_form": ["区分弹力带、支撑和自由重量划船。", "观察肩肘活动；耸肩结论需要可靠的肩抬高观测。", "不能把某个杠铃变式的轨迹要求强制用于弹力带。"],
    "lunge_form": ["区分前后弓步和分腿蹲。", "确认支撑侧及当前阶段再比较左右。", "左右差值是观测，不能直接诊断代偿；缺少平衡轨迹时不评价稳定趋势。"],
    "plank_form": ["前臂平板、侧平板和死虫式分别评估。", "检查躯干下沉/抬髋需要相应形状指标，保持时间必须以秒单独给出。", "呼吸和疼痛来自用户报告，不能从角度推断。"],
    "balance_form": ["确认是否有支撑及安全站立环境。", "单帧不能表示摆动；时间序列范围也不自动等于跌倒风险。", "短暂左右差异不是伤病证据。"],
}
POSTURE_FIELDS = {
    "curl_form": ["load_kg", "phase_sequence", "trunk_shape", "support_side"],
    "squat_form": ["heel_contact", "foot_keypoints", "trunk_shape", "phase_sequence"],
    "hinge_form": ["trunk_shape", "load_kg", "implement_trajectory", "phase_sequence"],
    "push_form": ["shoulder_hip_ankle_keypoints", "upper_arm_abduction", "trunk_shape"],
    "pull_form": ["trunk_shape", "implement_trajectory", "resistance_description"],
    "lunge_form": ["support_side", "sides_same_phase", "foot_keypoints", "balance_trajectory"],
    "plank_form": ["shoulder_elbow_keypoints", "trunk_shape", "hold_duration_seconds"],
    "balance_form": ["support_used", "balance_trajectory", "hold_duration_seconds"],
}


def measurement_review(data):
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise InputError("metadata 必须是对象。")
    camera = metadata.get("camera_view", "unknown")
    dimension = metadata.get("measurement_space", "2d")
    if camera not in {"front", "side", "rear", "oblique", "unknown"} or dimension not in {"2d", "3d"}:
        raise InputError("camera_view 或 measurement_space 无效。")
    expert = BY_EXERCISE[data["exercise_id"]]
    global_convention = metadata.get("angle_convention", "unknown")
    classification = metadata.get("classification_confidence")
    if classification is not None and (type(classification) not in {int, float} or not 0 <= classification <= 1):
        raise InputError("classification_confidence 必须在 0 到 1 之间。")
    details = []
    for name, observation in data["joints"].items():
        definition = observation.get("definition", "unknown")
        if definition == "unknown" and name in FLEXION:
            definition = {"internal_flexion_degrees":"flexion_from_extension", "anatomical_flexion_degrees":"flexion_from_extension", "included_segment_angle":"included_segment_angle"}.get(global_convention, "unknown")
        if definition != "unknown" and definition not in DEFINITIONS:
            raise InputError(f"{name}.definition 不在支持的角度定义中。")
        reasons = []
        if classification is not None and classification < CONFIDENCE_FLOOR:
            reasons.append("运动类型识别不确定，应先由 A 组或用户确认动作变式。")
        if observation.get("confidence", 1) < CONFIDENCE_FLOOR:
            reasons.append("关键点置信度低于项目数据质量门槛；不是动作是否正确的界限。")
        if definition == "unknown":
            reasons.append("未说明角度零点和定义，数值不能直接解释为解剖角度。")
        elif name in FLEXION and definition not in {"flexion_from_extension", "included_segment_angle"}:
            reasons.append("屈曲字段的角度定义不匹配。")
        elif name == "trunk_inclination" and definition not in {"inclination_from_vertical", "inclination_from_horizontal"}:
            reasons.append("躯干倾角需要说明相对水平或竖直方向。")
        elif name in FRONTAL | {"trunk_sag_angle", "trunk_sway_deg"} and definition != "projected_deviation":
            reasons.append("代理偏移角需要定义基准及估计方法。")
        if dimension == "3d" and metadata.get("calibrated") is not True:
            reasons.append("3D 测量未声明完成坐标/相机标定。")
        if dimension == "2d":
            if name in FRONTAL and camera not in {"front", "rear"}:
                reasons.append("该正面代理指标缺少适合的正面或背面视角。")
            elif name in SAGITTAL and camera != "side":
                reasons.append("该矢状面指标缺少适合的侧面视角。")
            elif camera == "unknown":
                reasons.append("相机视角未知。")
        if data["phase"] == "unknown":
            reasons.append("动作阶段未知，无法套用阶段姿势要求。")
        details.append({"joint":name, "angle_deg":observation["angle_deg"], "confidence":observation.get("confidence",1), "definition":definition, "interpretable":not reasons, "limitations":reasons, "relevant_to_specialist":name in expert.required_observations})
    comparable = {row["joint"]:row for row in details if row["interpretable"]}
    symmetry = []
    if all(name in comparable for name in ("left_knee_flexion", "right_knee_flexion")) and comparable["left_knee_flexion"]["definition"] == comparable["right_knee_flexion"]["definition"] and metadata.get("sides_same_phase") is True:
        symmetry.append({"metric":"left_right_knee_difference_deg", "value":abs(comparable["left_knee_flexion"]["angle_deg"]-comparable["right_knee_flexion"]["angle_deg"]), "interpretation":"同定义且同阶段的左右差值，不是错误阈值或伤病判断。"})
    usable = any(row["interpretable"] and row["relevant_to_specialist"] for row in details)
    return {"camera_view":camera, "measurement_space":dimension, "classification_confidence":classification, "measurements":details, "comparable_differences":symmetry,
            "has_interpretable_specialist_measurement":usable, "checklist":CHECKLISTS[expert.specialist_id],
            "missing_specialist_observations":[name for name in expert.required_observations if name not in data["joints"] and name not in metadata],
            "missing_posture_observations":[name for name in POSTURE_FIELDS[expert.specialist_id] if name not in metadata],
            "note":"角度仅描述观测。没有经过变式、个体、视角和测量定义校准的普适正确角度。"}

"""Describe what a pose measurement supports without inventing form thresholds."""
from app.engine import InputError
from app.experts.movement import BY_EXERCISE
from app.movement_thresholds import threshold_profile

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
    "lower_body_general": ["仅识别到弓步动作家族，未确认前后方向、支撑侧或阶段。", "不能从类别标签判断膝路径、平衡、次数或动作是否正确。"],
    "upper_body_push_general": ["区分肩推与侧平举，不根据类别推断器械和肩关节角度。", "没有专项测量时只给舒适范围和循序渐进的一般建议。"],
    "upper_body_pull_general": ["划船与引体向上的支撑、握法和器械不同。", "类别识别不能确认肩胛轨迹、肘路径、次数或负重。"],
    "arms_general": ["先确认三头伸展变式和器械。", "不能从类别推断肘关节极限位置或负重是否合适。"],
    "core_general": ["仰卧起坐类别不等于完整重复次数或脊柱动作质量。", "舒适度和疼痛只能来自用户报告。"],
    "cardio_general": ["节律活动的类别不等于准确步数、次数、心率或强度。", "跳绳的绳子不在骨架观测中，不能确认器械使用。"],
    "yoga_general": ["树式和三角式只识别姿势家族。", "保持时间、支撑、平衡趋势和安全性需要额外观测。"],
    "full_body_general": ["波比跳含多个阶段，类别标签不能确认每个阶段或完整次数。", "没有阶段和关键点证据时不评价俯卧撑、跳跃或落地质量。"],
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
    "lower_body_general": ["exercise_variant", "support_side", "phase_sequence"],
    "upper_body_push_general": ["exercise_variant", "equipment", "phase_sequence"],
    "upper_body_pull_general": ["exercise_variant", "equipment", "phase_sequence"],
    "arms_general": ["exercise_variant", "equipment", "phase_sequence"],
    "core_general": ["phase_sequence", "reported_comfort"],
    "cardio_general": ["duration_seconds", "equipment", "reported_exertion"],
    "yoga_general": ["hold_duration_seconds", "support_used", "balance_trajectory"],
    "full_body_general": ["phase_sequence", "landing_observations"],
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
    profile = threshold_profile(data["exercise_id"])
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
    target_checks = _target_checks(profile, details, data, camera)
    return {"camera_view":camera, "measurement_space":dimension, "classification_confidence":classification, "guidance_level":expert.guidance_level, "measurements":details, "comparable_differences":symmetry,
            "has_interpretable_specialist_measurement":usable, "checklist":CHECKLISTS[expert.specialist_id],
            "missing_specialist_observations":[name for name in expert.required_observations if name not in data["joints"] and name not in metadata],
            "missing_posture_observations":[name for name in POSTURE_FIELDS[expert.specialist_id] if name not in metadata],
            "threshold_profile":profile,
            "target_checks":target_checks,
            "note":"角度仅描述观测。没有经过变式、个体、视角和测量定义校准的普适正确角度。"}


def _target_checks(profile, details, data, camera):
    if profile is None:
        return [{"status":"non_numeric_guidance", "profile_status":"not_in_scoped_threshold_set",
                 "message":"该动作没有配置项目数值目标；按专家能力边界提供定性或通用建议。"}]
    if profile.get("status") != "provisional_numeric_proxy":
        return [{"status":"non_numeric_guidance", "profile_status":profile.get("status"),
                 "cue":profile.get("cue", "当前动作没有经过审核的数值目标。"),
                 "message":"该动作不支持数值化通过/不通过判断。"}]

    observed = {row["joint"]: row for row in details}
    checks = []
    for target in profile.get("evaluation", []):
        metric_names = target.get("metrics", [target.get("metric")])
        phase = data["phase"]
        valid_phase = phase in target.get("phase_any_of", [target.get("phase")])
        expected_definition = target.get("definition")
        candidates = [observed[name] for name in metric_names if name in observed]
        reliable = [row for row in candidates if row["interpretable"]
                    and row["confidence"] >= target.get("confidence_min", CONFIDENCE_FLOOR)
                    and row["definition"] == expected_definition]
        if not valid_phase:
            checks.append({"metrics":metric_names, "status":"insufficient_evidence", "reason":"phase_mismatch",
                           "phase":phase, "required_phases":target.get("phase_any_of", [target.get("phase")]),
                           "message":"当前阶段不适用于此目标角度比较。"})
            continue
        if not reliable:
            reasons = sorted({reason for row in candidates for reason in row["limitations"]})
            if candidates and not reasons:
                reasons = ["置信度不足或角度定义与阈值卡不一致。"]
            if camera == "unknown":
                reasons.append("未提供相机视角。")
            checks.append({"metrics":metric_names, "status":"insufficient_evidence", "reason":"measurement_unavailable",
                           "limitations":list(dict.fromkeys(reasons)), "message":"当前观测不足以判定是否达到项目目标。"})
            continue

        if target.get("aggregation") == "mean_of_reliable_sides":
            value = sum(row["angle_deg"] for row in reliable) / len(reliable)
            values = {row["joint"]:row["angle_deg"] for row in reliable}
        else:
            # Per-arm goals remain independent; never average alternating-arm motion.
            values = {row["joint"]:row["angle_deg"] for row in reliable}
            value = next(iter(values.values())) if len(values) == 1 else None
        operator = target["operator"]
        limit = target["value_deg"]
        def within(number):
            return number <= limit if operator == "<=" else number >= limit
        passed = within(value) if value is not None else all(within(number) for number in values.values())
        checks.append({"metrics":metric_names, "status":"within_project_target" if passed else "outside_project_target",
                       "observed_deg":round(value, 1) if value is not None else None,
                       "observed_by_metric_deg":{name:round(number, 1) for name, number in values.items()},
                       "excluded_metrics":[name for name in metric_names if name in observed and observed[name] not in reliable],
                       "target":{"operator":operator, "angle_deg":limit}, "phase":phase,
                       "definition":expected_definition, "confidence_min":target.get("confidence_min", CONFIDENCE_FLOOR),
                       "source_ids":target.get("source_ids", []),
                       "caveat":"仅表示是否达到项目暂定角度代理目标，不代表普适动作标准、医学结论或安全判断。"})
    return checks

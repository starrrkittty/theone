"""Exercise-specific observation protocols, not clinical angle standards."""

PROTOCOLS = {
    "squat": {"label":"深蹲", "preferred_view":"side", "views":{
        "side":["可见侧膝屈伸轨迹", "动作周期", "躯干投影倾斜"],
        "front":["双侧运动同步", "膝与足的投影对齐"]}},
    "pushup": {"label":"俯卧撑", "preferred_view":"side", "views":{
        "side":["可见侧肘屈伸轨迹", "动作周期", "肩髋踝投影连线"],
        "front":["双侧肘运动同步"]}},
    "plank": {"label":"平板支撑", "preferred_view":"side", "views":{
        "side":["持续时间", "肩髋踝投影连线"], "front":["双侧支撑可见性"]}},
    "bicep_curl": {"label":"弯举", "preferred_view":"front", "views":{
        "front":["双侧肘屈伸轨迹", "动作周期", "双侧运动同步"],
        "side":["可见侧肘屈伸轨迹", "动作周期", "上臂与躯干投影变化"]}},
    "alternate_bicep_curl": {"label":"交替弯举", "preferred_view":"front", "views":{
        "front":["双侧肘屈伸轨迹", "交替顺序", "动作周期"]}},
}


def view_policy(exercise, profile, observed, requested=None):
    view = {"frontal":"front", "profile_left":"side", "profile_right":"side"}.get(observed, "unknown")
    spec = PROTOCOLS.get(exercise, {})
    supported = view in spec.get("views", {})
    if profile == "frontal_v1":
        supported = view == "front"
    return {"profile":profile or "unspecified", "estimated_view":observed or "unknown",
            "declared_view":requested or "auto", "preferred_view":spec.get("preferred_view"),
            "expected_view":"front" if profile == "frontal_v1" else spec.get("preferred_view"),
            "method":"heuristic_from_image_landmarks_not_calibrated",
            "status":"supported" if supported else "unverified",
            "supported_observations":spec.get("views", {}).get(view, []),
            "limitations":["单目角度未经外部标定，不能当作真实解剖角度",
                           "侧面不能评价双侧对称或膝内扣；正面不能确认深度方向的动作幅度",
                           "遮挡关节不可评价；未发现错误不表示姿势正确"],
            "recommended_setup":"固定机位、全身入镜、保留手脚边距、避免遮挡；侧面朝向任一侧均可"}

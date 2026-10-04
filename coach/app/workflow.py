from app.agents import service
from app.group_adapters import from_group_a, from_group_e_profile, to_group_c_live_event, to_group_d_view


def run_workflow(payload):
    if not isinstance(payload, dict):
        raise ValueError("输入必须是 JSON 对象")
    result = {}
    payload = dict(payload)
    if payload.get("user_id"):
        for key in ("movement", "report", "profile", "nutrition"):
            if isinstance(payload.get(key), dict):
                payload[key] = {"user_id": payload["user_id"], **payload[key]}
    movement = None
    if "movement" in payload:
        movement = service.run("movement", from_group_a(payload["movement"]))
        result["movement"] = movement
        result["group_c_event"] = to_group_c_live_event(movement)
    if "report" in payload:
        report = dict(payload["report"])
        if movement:
            report["movement_observations"] = report.get("movement_observations", []) + [{"status": "caution" if any(f["severity"] == "caution" for f in movement["findings"]) else movement["status"], "summary": "；".join(cue["text"] for cue in movement["cues"])}]
            if movement["status"] == "stop":
                report["reported_symptoms"] = list(set(report.get("reported_symptoms", []) + payload["movement"].get("reported_symptoms", [])))
        result["report"] = service.run("report", report)
        result["group_d_view"] = to_group_d_view(result["report"])
    if "profile" in payload:
        plan = from_group_e_profile(payload["profile"])
        plan["context"] = {**plan.get("context", {}), "latest_report": result.get("report"), "current_movement": movement}
        if movement and movement["status"] == "stop":
            plan["reported_symptoms"] = payload["movement"].get("reported_symptoms", [])
        result["plan"] = service.run("plan", plan)
    if "nutrition" in payload:
        nutrition = dict(payload["nutrition"])
        nutrition["context"] = {**nutrition.get("context", {}), "latest_report": result.get("report"), "plan": result.get("plan")}
        result["nutrition"] = service.run("nutrition", nutrition)
    if not result:
        raise ValueError("需要 movement、report、profile 或 nutrition 至少一个字段")
    return result

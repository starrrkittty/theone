import argparse
import json
from pathlib import Path

from app.agents import service
from app.engine import experts_catalog
from app.group_adapters import from_group_a, from_group_e_profile, to_group_c_live_event, to_group_d_view

ROOT = Path(__file__).parent


def dump(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="B-group fitness coach demo")
    parser.add_argument("command", choices=["all", "movement", "report", "plan", "nutrition", "experts"])
    args = parser.parse_args()
    if args.command in ("all", "movement"):
        payload = json.loads((ROOT / "examples" / "squat_input.json").read_text(encoding="utf-8"))
        result = service.run("movement", from_group_a(payload))
        dump({"group_a_input": payload, "group_b_analysis": result, "group_c_live_event": to_group_c_live_event(result)})
    if args.command in ("all", "report"):
        request = json.loads((ROOT / "examples" / "workout_session.json").read_text(encoding="utf-8"))
        result = service.run("report", request)
        dump({"group_b_report": result, "group_d_view_model": to_group_d_view(result)})
    if args.command in ("all", "plan"):
        profile = json.loads((ROOT / "examples" / "user_profile.json").read_text(encoding="utf-8"))
        dump({"group_e_profile": profile, "group_b_phase_plan": service.run("plan", from_group_e_profile(profile))})
    if args.command in ("all", "nutrition"):
        request = json.loads((ROOT / "examples" / "nutrition_request.json").read_text(encoding="utf-8"))
        dump({"group_b_nutrition_advice": service.run("nutrition", request)})
    if args.command in ("all", "experts"):
        dump(experts_catalog())


if __name__ == "__main__":
    main()

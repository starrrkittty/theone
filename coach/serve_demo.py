import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from app.workflow import run_workflow
from app.history import delete, memory_overview, recent, save_profile
from app.group_adapters import from_group_a, group_e_contract
from app.chat import respond as chat_respond
from app.engine import validate_movement
from app.movement_evidence import measurement_review
from app.routing import resolve_movement, resolve_task

from app.agents import service
from app.model_client import ConfigurationError, ModelError
from app.engine import InputError, experts_catalog


ROOT = Path(__file__).parent
CASE_DIRECTORY = ROOT / "examples"
CASE_CATALOG = (
    ("squat_target_met", "深蹲 / 基准：侧面角度可解释", "movement", "b-agent-cases/squat_target_met.json", "within_project_target"),
    ("squat_target_missed", "深蹲 / 对照：较浅角度", "movement", "b-agent-cases/squat_target_missed.json", "outside_project_target"),
    ("squat_insufficient_evidence", "深蹲：视角证据不足", "movement", "b-agent-cases/squat_insufficient_evidence.json", "insufficient_evidence"),
    ("squat_low_confidence", "深蹲：关键点置信度低", "movement", "b-agent-cases/squat_low_confidence.json", "insufficient_evidence"),
    ("plank_explicit_sag", "平板支撑 / 基准：躯干代理量较小", "movement", "b-agent-cases/plank_explicit_sag.json", "within_project_target"),
    ("plank_explicit_sag_contrast", "平板支撑 / 对照：躯干代理量较大", "movement", "b-agent-cases/plank_explicit_sag_contrast.json", "工程项目目标对照，不是医学判断"),
    ("semantic_lunge", "弓步类别 / 基准：类别级观测", "movement", "b-agent-cases/semantic_lunge.json", "non_numeric_guidance"),
    ("semantic_lunge_uncertain", "弓步类别 / 对照：识别置信度偏低", "movement", "b-agent-cases/semantic_lunge_uncertain.json", "识别置信度对照，不输出姿势纠错"),
    ("hip_hinge_controlled", "髋铰链 / 基准：侧面观测", "movement", "b-agent-cases/hip_hinge_controlled.json", "专项髋、膝和躯干观测；不推断负重风险"),
    ("hip_hinge_larger_trunk_angle", "髋铰链 / 对照：躯干倾角较大", "movement", "b-agent-cases/hip_hinge_larger_trunk_angle.json", "角度变化仅为观测，不定义危险姿势"),
    ("push_up_observed", "俯卧撑 / 基准：底部肘角观测", "movement", "b-agent-cases/push_up_observed.json", "专项肘部观测；全身排列仍有限"),
    ("push_up_larger_elbow_range", "俯卧撑 / 对照：不同肘角观测", "movement", "b-agent-cases/push_up_larger_elbow_range.json", "角度比较仅是项目暂定代理"),
    ("band_row_front", "弹力带划船 / 基准：正面肩部代理量", "movement", "b-agent-cases/band_row_front.json", "肩抬高是相机代理量，不代表肩伤"),
    ("band_row_larger_shoulder_proxy", "弹力带划船 / 对照：肩部代理量变化", "movement", "b-agent-cases/band_row_larger_shoulder_proxy.json", "项目启发式不是通用动作阈值"),
    ("forward_lunge_side", "前弓步 / 基准：侧面支撑腿观测", "movement", "b-agent-cases/forward_lunge_side.json", "不套用普适角度目标"),
    ("forward_lunge_front_proxy", "前弓步 / 对照：正面膝路径代理量", "movement", "b-agent-cases/forward_lunge_front_proxy.json", "2D 正面代理量有视角局限"),
    ("alternate_bicep_curl", "交替弯举 / 基准：左臂上举阶段", "movement", "b-agent-cases/alternate_bicep_curl.json", "按活动侧解释；另一侧不要求同步"),
    ("alternate_bicep_curl_right_active", "交替弯举 / 对照：右臂上举阶段", "movement", "b-agent-cases/alternate_bicep_curl_right_active.json", "左右手分阶段，不要求同步"),
    ("single_leg_balance_front", "单腿站立 / 基准：正面平衡代理量", "movement", "b-agent-cases/single_leg_balance_front.json", "单帧不能评估摆动趋势或跌倒风险"),
    ("single_leg_balance_larger_sway", "单腿站立 / 对照：平衡代理量变化", "movement", "b-agent-cases/single_leg_balance_larger_sway.json", "不推断跌倒风险"),
    ("jumping_jack_category", "开合跳 / 基准：仅动作类别", "movement", "b-agent-cases/jumping_jack_category.json", "类别级建议；不验证次数、绳具或心率"),
    ("jumping_jack_category_uncertain", "开合跳 / 对照：类别置信度偏低", "movement", "b-agent-cases/jumping_jack_category_uncertain.json", "不生成关节角度纠错"),
    ("yoga_tree_category", "瑜伽树式 / 基准：仅姿势家族", "movement", "b-agent-cases/yoga_tree_category.json", "不推断平衡质量"),
    ("yoga_tree_unsupported", "瑜伽树式 / 对照：无支撑信息", "movement", "b-agent-cases/yoga_tree_unsupported.json", "不推断平衡能力"),
    ("training_plan", "训练规划：新手基础力量与近期恢复", "plan", "training_plan_strength.json", "计划符合目标、天数、时长和近期背景"),
    ("workout_report", "训练汇报：多动作、目标与主观用力", "report", "workout_report_personalized.json", "统计事实由程序计算并校验"),
    ("nutrition_advice", "饮食建议：素食、花生过敏与食堂预算", "nutrition", "nutrition_personalized.json", "保留过敏原、偏好、预算和就餐条件"),
)
class DemoHandler(BaseHTTPRequestHandler):
    server_version = "BGroupDemo/1.0"

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/status":
            try:
                self._json(200, service.client.status())
            except ConfigurationError as exc:
                self._json(503, {"error": str(exc)})
            return
        if path == "/" or path == "/index.html":
            self._send(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/api/experts":
            self._json(200, experts_catalog())
            return
        if path == "/api/cases":
            cases = []
            for case_id, title, task, filename, expected in CASE_CATALOG:
                payload = json.loads((CASE_DIRECTORY / filename).read_text(encoding="utf-8"))
                cases.append({
                    "id": case_id,
                    "title": title,
                    "task": task,
                    "expected": expected,
                    "payload": payload,
                })
            self._json(200, {"cases": cases})
            return
        if path == "/testbench" or path == "/testbench.html":
            self._send(200, (ROOT / "testbench.html").read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/api/integration/contract":
            self._json(200, group_e_contract())
            return
        if path == "/api/history":
            try:
                user = parse_qs(urlparse(self.path).query).get("user_id", [""])[0]
                self._json(200, {"reports": recent(user)})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            return
        if path == "/api/memory":
            try:
                user = parse_qs(urlparse(self.path).query).get("user_id", [""])[0]
                self._json(200, memory_overview(user))
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            return
        if path == "/chat" or path == "/chat.html":
            self._send(200, (ROOT / "chat.html").read_bytes(), "text/html; charset=utf-8")
            return
        self._json(404, {"error": "Not found"})

    def do_POST(self):
        routes = {
            "/api/movement/analyze": "movement",
            "/api/plans/phase": "plan",
            "/api/nutrition/advice": "nutrition",
            "/api/workouts/summary": "report",
        }
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise ValueError("Request body is empty or too large")
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            path = urlparse(self.path).path
            if path == "/api/movement/batch":
                cases = data.get("cases")
                analyze = data.get("analyze_with_agent", False)
                if not isinstance(cases, list) or not 1 <= len(cases) <= 40:
                    raise ValueError("cases 必须是 1 到 40 项的数组。")
                if type(analyze) is not bool:
                    raise ValueError("analyze_with_agent 必须是布尔值。")
                results = []
                for item in cases:
                    case_id = item.get("id", "") if isinstance(item, dict) else ""
                    try:
                        if not isinstance(item, dict) or not isinstance(item.get("payload"), dict):
                            raise ValueError("每项必须包含 JSON 对象 payload。")
                        movement_payload = from_group_a(item["payload"])
                        if analyze:
                            result = service.run("movement", movement_payload)
                        else:
                            _, route = resolve_movement(movement_payload)
                            result = {"route": route, "measurement_review": route["measurement_review"],
                                      "agent": {"mode": "measurement_tool", "model_called": False}}
                        results.append({"id": case_id, "ok": True, "result": result})
                    except (ConfigurationError, ModelError, InputError, ValueError, TypeError, KeyError) as exc:
                        results.append({"id": case_id, "ok": False, "error": str(exc)})
                self._json(200, {"total": len(results), "succeeded": sum(item["ok"] for item in results),
                                 "analyzed_by_agent": analyze, "results": results})
                return
            elif path == "/api/movement/evidence":
                data = from_group_a(data)
                validate_movement(data)
                result = {"measurement_review":measurement_review(data), "agent":{"mode":"measurement_tool", "model_called":False}}
            elif path == "/api/movement/route":
                _, route = resolve_movement(data)
                result = {"route": route}
            elif path == "/api/plans/route":
                _, route = resolve_task("plan", data)
                result = {"route": route}
            elif path == "/api/nutrition/route":
                _, route = resolve_task("nutrition", data)
                result = {"route": route}
            elif path == "/api/workouts/route":
                _, route = resolve_task("report", data)
                result = {"route": route}
            elif path == "/api/chat":
                result = chat_respond(data, service.client)
            elif path == "/api/memory/profile":
                result = {"profile": save_profile(data.get("user_id"), data.get("profile"))}
            elif path in {"/api/memory/delete", "/api/history/delete"}:
                delete(data.get("user_id"))
                result = {"deleted": True}
            elif path == "/api/workflow":
                result = run_workflow(data)
            elif path in routes:
                result = service.run(routes[path], from_group_a(data) if routes[path] == "movement" else data)
            else:
                self._json(404, {"error": "Not found"})
                return
            self._json(200, result)
        except ConfigurationError as exc:
            self._json(503, {"error": str(exc)})
        except ModelError as exc:
            self._json(502, {"error": str(exc)})
        except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError, InputError) as exc:
            self._json(400, {"error": str(exc)})

    def _json(self, status, value):
        self._send(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _send(self, status, content, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        print("%s - %s" % (self.log_date_time_string(), format % args))


if __name__ == "__main__":
    address = (os.environ.get("FITNESS_DEMO_HOST", "127.0.0.1"), int(os.environ.get("FITNESS_DEMO_PORT", "8765")))
    server = ThreadingHTTPServer(address, DemoHandler)
    print(f"B-group demo ready at http://{address[0]}:{address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

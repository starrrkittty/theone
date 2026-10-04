"""Offline integration checks with an explicit fake model provider, never real AI."""
import copy
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.agents import AgentService
from app.coaching import workout_summary
from app.engine import InputError
from app.experts.movement import BY_EXERCISE
from app.model_client import ModelClient, ModelError, ConfigurationError
from app.output_contracts import validate, NUMBER
import app.history as history
from serve_demo import DemoHandler

ROOT = Path(__file__).parent
CALLS = []
INVALID_RESPONSES = 0


def fixture(context):
    task, data = context["task"], context["input"]
    if task == "movement":
        return {"schema_version":"1.0", "session_id":data["session_id"], "rep_index":data["rep_index"], "exercise_id":data["exercise_id"], "routed_to":[BY_EXERCISE[data["exercise_id"]].specialist_id], "status":"limited" if not data["joints"] else "assessed", "overall_score":None,
                "findings":[], "cues":[{"priority":2,"text":"模拟模型反馈，仅用于接口验证", "rationale":"测试夹具"}], "safety_messages":[], "limitations":["模拟结果"], "missing_observations":[]}
    if task == "report":
        return {**context["computed_facts"], "next_session_suggestion":"模拟建议", "disclaimer":"模拟模型结果"}
    if task == "nutrition":
        return {"schema_version":"1.0", "status":"general_guidance", "message":"模拟饮食结果", "suggestions":["测试建议"], "dietary_preferences":data.get("dietary_preferences",[]), "exclude_allergens":data.get("allergies",[]), "source_ids":["who_healthy_diet_2024"], "meals":[{"type":"breakfast","suggestion":"测试早餐","reason":"测试"}], "substitutions":[], "training_day_advice":"测试", "hydration_note":"测试"}
    return {"schema_version":"1.0", "phase":"adaptation", "duration_weeks":2, "goal":data["goal"], "weekly_sessions":data["days_per_week"], "minutes_per_session":data["minutes_per_session"], "focus":"模拟阶段", "weekly_structure":[{"day":day,"type":"full_body_strength" if i<data["days_per_week"] else "rest_or_easy_walk"} for i,day in enumerate(["mon","tue","wed","thu","fri","sat","sun"])], "session_template":{"warmup_minutes":3,"main":[{"pattern":"squat","exercise_option":"sit_to_stand","sets":1,"reps":"6","effort_target":"轻松"}],"cooldown_minutes":2}, "progression_rule":"模拟进阶", "limitations":data.get("limitations",[]), "review_note":"测试夹具"}


class FakeProvider(BaseHTTPRequestHandler):
    def do_POST(self):
        global INVALID_RESPONSES
        body=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        CALLS.append({"path":self.path,"auth":self.headers.get("Authorization"),"body":body})
        context=json.loads(body["messages"][1]["content"])
        output=fixture(context)
        if INVALID_RESPONSES:
            INVALID_RESPONSES-=1
            output={"broken":True}
        response=json.dumps({"model":"fake-test-model","choices":[{"finish_reason":"stop","message":{"content":json.dumps(output,ensure_ascii=False)}}],"usage":{"total_tokens":10}}).encode()
        self.send_response(200)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self,*args):
        pass


class Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider=ThreadingHTTPServer(("127.0.0.1",0),FakeProvider)
        cls.web=ThreadingHTTPServer(("127.0.0.1",0),DemoHandler)
        for server in (cls.provider,cls.web):
            threading.Thread(target=server.serve_forever,daemon=True).start()
        cls.environment=patch.dict(os.environ,{"FITNESS_API_KEY":"fake-test-key","FITNESS_BASE_URL":f"http://127.0.0.1:{cls.provider.server_port}/v1","FITNESS_MODEL":"fake-test-model"})
        cls.environment.start()
        cls.test_directory=ROOT/".verification-data"
        cls.test_directory.mkdir(exist_ok=True)
        cls.storage=patch.object(history,"DATABASE",cls.test_directory/"history.sqlite3")
        cls.storage.start()

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        cls.storage.stop()
        for server in (cls.provider,cls.web):
            server.shutdown()
            server.server_close()
        (cls.test_directory/"history.sqlite3").unlink(missing_ok=True)
        cls.test_directory.rmdir()

    def setUp(self):
        global INVALID_RESPONSES
        INVALID_RESPONSES=0
        CALLS.clear()

    def example(self,name):
        return json.loads((ROOT/"examples"/f"{name}.json").read_text(encoding="utf-8"))

    def request(self,path,data=None):
        request=Request(f"http://127.0.0.1:{self.web.server_port}"+path,data=json.dumps(data).encode() if data is not None else None,headers={"Content-Type":"application/json"})
        with urlopen(request,timeout=10) as response:
            return json.loads(response.read())

    def test_all_tasks_use_model_skills_and_knowledge(self):
        requests=[("movement/analyze",self.example("squat_input")),("plans/phase",self.example("user_profile")),("workouts/summary",self.example("workout_session")),("nutrition/advice",self.example("nutrition_request"))]
        for route,data in requests:
            with self.subTest(route=route):
                result=self.request("/api/"+route,data)
                self.assertTrue(result["agent"]["model_called"])
                self.assertEqual(result["agent"]["mode"],"ai_agent")
                call=CALLS[-1]
                self.assertEqual(call["path"],"/v1/chat/completions")
                self.assertEqual(call["auth"],"Bearer fake-test-key")
                context=json.loads(call["body"]["messages"][1]["content"])
                self.assertTrue(context["retrieved_knowledge"])
                self.assertIn("#",call["body"]["messages"][0]["content"])

    def test_one_repair_and_terminal_failure(self):
        global INVALID_RESPONSES
        INVALID_RESPONSES=1
        result=AgentService().run("movement",self.example("squat_input"))
        self.assertEqual(result["agent"]["attempts"],2)
        INVALID_RESPONSES=2
        with self.assertRaises(ModelError):
            AgentService().run("movement",self.example("squat_input"))

    def test_configuration_and_safety(self):
        with patch.dict(os.environ,{"FITNESS_API_KEY":""}):
            with self.assertRaises(HTTPError) as caught:
                self.request("/api/movement/analyze",self.example("squat_input"))
            self.assertEqual(caught.exception.code,503)
            caught.exception.close()
        movement=self.example("squat_input")
        movement["reported_symptoms"]=[" CHEST_PAIN "]
        result=AgentService().run("movement",movement)
        self.assertFalse(result["agent"]["model_called"])
        nutrition=self.example("nutrition_request")
        nutrition["medical_conditions"]=["medical restriction"]
        self.assertEqual(AgentService().run("nutrition",nutrition)["status"],"refer")
        self.assertFalse(CALLS)
        plan=self.example("user_profile")
        plan["context"]={"latest_report":{"reported_stop_symptom":True}}
        self.assertEqual(AgentService().run("plan",plan)["status"],"stop")
        self.assertFalse(CALLS)

    def test_factual_integrity_and_bad_inputs(self):
        service=AgentService()
        data=self.example("squat_input")
        output=fixture({"task":"movement","input":data})
        output["rep_index"]+=1
        with self.assertRaises(ValueError):
            service._check_facts("movement",data,output,None,[],"squat_form")
        with self.assertRaises(ValueError):
            validate(float("nan"),NUMBER)
        report=self.example("workout_session")
        report["sets"]=[{"exercise_id":"squat","reps":-1}]
        with self.assertRaises(InputError):
            service.run("report",report)

    def test_history_idempotency_and_personalization(self):
        data=self.example("workout_session")
        data["user_id"]="integration-user"
        for _ in range(2):
            self.request("/api/workouts/summary",data)
        self.assertEqual(len(history.recent("integration-user")),1)
        plan=self.example("user_profile")
        plan["user_id"]="integration-user"
        self.request("/api/plans/phase",plan)
        self.assertEqual(len(json.loads(CALLS[-1]["body"]["messages"][1]["content"])["context"]["stored_reports"]),1)
        history.delete("integration-user")
        self.assertEqual(history.recent("integration-user"),[])

    def test_group_workflow(self):
        result=self.request("/api/workflow",{"movement":self.example("squat_input"),"report":self.example("workout_session"),"profile":self.example("user_profile"),"nutrition":self.example("nutrition_request")})
        self.assertEqual(set(result),{"movement","report","plan","nutrition","group_c_event","group_d_view"})
        self.assertEqual(len(CALLS),4)

    def test_all_specialist_routes(self):
        for exercise in BY_EXERCISE:
            data=self.example("squat_input")
            data["exercise_id"]=exercise
            data["joints"]={}
            result=AgentService().run("movement",data)
            self.assertEqual(result["routed_to"],[BY_EXERCISE[exercise].specialist_id])
            self.assertEqual(result["status"],"limited")

    def test_citation_and_measurement_guards(self):
        data=self.example("squat_input")
        output=fixture({"task":"movement","input":data})
        output["findings"]=[{"joint":"knee_flexion","observed":999,"confidence":.91,"source_ids":[],"severity":"info"}]
        with self.assertRaises(ValueError):
            AgentService()._check_facts("movement",data,output,None,[],"squat_form")
        output["findings"]=[]
        output["source_ids"]=["invented"]
        with self.assertRaises(ValueError):
            AgentService()._check_facts("movement",data,output,None,[],"squat_form")


if __name__=="__main__":
    unittest.main(verbosity=2)

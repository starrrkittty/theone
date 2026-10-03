"""End-to-end contract checks using an explicit fake LLM, not AI quality tests."""
import json
import math
from pathlib import Path

from fastapi.testclient import TestClient

from main import app
from api.routes import manager
from app.agents import AgentService
from verify_integration import fixture
import app.routers as coach_routes
import api.perception_routes as perception_routes
from perception.agent import PerceptionAgent


class FakePerceptionModel:
    def status(self):
        return {"configured":True}

    def complete(self, messages):
        return json.dumps({"tool":"finish", "decision":"handoff", "reason":"Explicit mock evidence check",
                           "observation_request":"none"}), {"model":"explicit-fake-perception"}
from .test_recognition_regressions import curl_pose


class FakeModel:
    def __init__(self):
        self.calls = []

    def complete(self, messages):
        self.calls.append(messages)
        context = json.loads(messages[-1]["content"])
        output = fixture(context)
        if context["task"] == "movement":
            output["status"] = "limited" if not context["measurement_review"]["has_interpretable_specialist_measurement"] else "assessed"
        return json.dumps(output, ensure_ascii=False), {"model":"explicit-fake-model"}


def test_pose_websocket_through_adapter_skills_and_specialist(monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(coach_routes, "service", AgentService(model))
    monkeypatch.setattr(perception_routes, "ModelClient", FakePerceptionModel)
    monkeypatch.setattr(perception_routes, "PerceptionAgent", lambda: PerceptionAgent(FakePerceptionModel()))
    monkeypatch.setattr(manager, "should_rate_limit", lambda client_id:False)
    clock = [1700000000.0]
    monkeypatch.setattr("time.time", lambda:clock[0])
    client = TestClient(app)
    report = None
    with client.websocket_connect("/api/ws/pose/chain-test") as ws:
        for index in range(90):
            clock[0] += 1/30
            ws.send_json({"landmarks":curl_pose(115+55*math.cos(index/15)), "timestamp":clock[0]*1000,
                          "client_probs":{"curl-stand":.99}})
            result = ws.receive_json()
            if result["action_report"]["recognition_status"] == "confirmed":
                report = result["action_report"]
        assert report is not None and report["recognized_exercise"] == "bicep_curl"
        normalized = client.post("/api/agent-a/normalize",json={"action_report":report})
        assert normalized.status_code == 200
        assert normalized.json()["movement"]["joints"]["left_elbow_flexion"]["definition"] == "included_segment_angle"
        feedback = client.post("/api/agent-a/coach",json={"action_report":report})
        assert feedback.status_code == 200, feedback.text
        assert feedback.json()["analysis"]["agent"]["specialist"] == "curl_form"
        assert feedback.json()["analysis"]["status"] == "limited"
        assert "Movement Report" in model.calls[0][0]["content"]
        assert json.loads(model.calls[0][1]["content"])["retrieved_knowledge"]
        ws.send_json({"landmarks":[],"timestamp":clock[0]*1000})
        lost = ws.receive_json()["action_report"]
        assert lost["recognition_status"] == "unknown"
        wait = client.post("/api/agent-a/coach",json={"action_report":lost})
        assert wait.json()["agent"]["model_called"] is False
        assert len(model.calls) == 1


def test_report_and_planning_load_their_runtime_skills(monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(coach_routes, "service", AgentService(model))
    client = TestClient(app)
    root = Path(__file__).resolve().parents[2]/"coach"/"examples"
    for file, endpoint, skill in (("workout_session.json","/api/workouts/summary","training-report"),
                                  ("user_profile.json","/api/plans/phase","training-plan")):
        payload = json.loads((root/file).read_text(encoding="utf-8"))
        reply = client.post(endpoint,json=payload)
        assert reply.status_code == 200, reply.text
        assert reply.json()["agent"]["skill"] == skill


def test_unknown_and_malformed_inputs_never_call_model(monkeypatch):
    model = FakeModel(); monkeypatch.setattr(coach_routes,"service",AgentService(model))
    client = TestClient(app)
    assert client.post("/api/agent-a/normalize",json={"schema_version":"v1","recognized_exercise":[]}).status_code == 422
    assert client.post("/api/agent-a/coach",json={"schema_version":"v1","recognition_status":"candidate"}).json()["status"] == "awaiting_recognition"
    assert not model.calls

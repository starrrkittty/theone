"""APP v1 contract checks with a deterministic model stand-in."""
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from main import app
from app import mobile


EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "contracts" / "app_coach_v1_examples.json"


@pytest.fixture
def fixture_data():
    return json.loads(EXAMPLES.read_text(encoding="utf-8"))


@pytest.fixture
def client(monkeypatch):
    uri = f"file:mobile-contract-{uuid4().hex}?mode=memory&cache=shared"
    anchor = sqlite3.connect(uri, uri=True)
    anchor.execute("CREATE TABLE results (scope TEXT, session TEXT, fingerprint TEXT, created REAL, response TEXT, PRIMARY KEY(scope, session))")
    monkeypatch.setattr(mobile, "connect", lambda: sqlite3.connect(uri, uri=True, timeout=3))
    monkeypatch.delenv("FITNESS_APP_DEV_TOKEN", raising=False)
    with TestClient(app, client=("127.0.0.1", 51000)) as api:
        yield api
    anchor.close()


def test_app_plan_is_executable_and_profile_is_projected(client, fixture_data, monkeypatch):
    sent = []

    def complete(messages):
        sent.append(json.loads(messages[1]["content"]))
        return json.dumps({"stage_name": "适应期", "headline": "练习深蹲", "reason": "以少量训练开始。",
                           "item": {"exercise_id": "squat", "title": "模型错误标题", "target_sets": 1,
                                    "target_reps": 6, "rest_seconds": 45}}, ensure_ascii=False), {}

    monkeypatch.setattr(mobile.service.client, "complete", complete)
    response = client.post("/api/app/v1/plan", json=fixture_data["plan_request"])
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "agent"
    assert body["item"]["exercise_id"] == "squat"
    assert body["item"]["title"] == "徒手深蹲"
    assert body["item"]["target_sets"] == 1
    assert body["item"]["id"].startswith(body["plan_id"])
    assert "diet_preference" not in sent[0]["facts"]["profile"]


def test_unexecutable_plan_retries_then_fails_without_fake_success(client, fixture_data, monkeypatch):
    calls = []

    def complete(messages):
        calls.append(1)
        return json.dumps({"stage_name": "适应期", "headline": "练习", "reason": "准备训练",
                           "item": {"exercise_id": "push_up", "title": "俯卧撑", "target_sets": 1,
                                    "target_reps": 6, "rest_seconds": 45}}, ensure_ascii=False), {}

    monkeypatch.setattr(mobile.service.client, "complete", complete)
    response = client.post("/api/app/v1/plan", json=fixture_data["plan_request"])
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "INVALID_MODEL_OUTPUT"
    assert len(calls) == 2


def test_no_item_plan_and_ordinary_nutrition_use_declared_sources(client, fixture_data, monkeypatch):
    def complete(messages):
        task = json.loads(messages[1]["content"])["task"]
        if task == "plan":
            return json.dumps({"stage_name": "待确认", "headline": "暂不安排训练",
                               "reason": "当前没有可执行项目。", "item": None}, ensure_ascii=False), {}
        return json.dumps({"focus": "regular_meals"}), {}

    monkeypatch.setattr(mobile.service.client, "complete", complete)
    planned = client.post("/api/app/v1/plan", json=fixture_data["plan_request"])
    ordinary = client.post("/api/app/v1/nutrition", json={"profile": fixture_data["profile"]})
    assert planned.status_code == ordinary.status_code == 200
    assert planned.json()["item"] is None
    assert planned.json()["source"] == ordinary.json()["source"] == "agent"


def test_plan_uses_completed_days_for_rest_and_excludes_unfinished_sessions(client, fixture_data, monkeypatch):
    history = json.loads(json.dumps(fixture_data["summary_request"]["session"]))
    request = json.loads(json.dumps(fixture_data["plan_request"]))
    request["local_date"] = "2026-10-03"
    request["history"] = [history]

    def unexpected(_):
        raise AssertionError("a completed training day should use a deterministic rest plan")

    monkeypatch.setattr(mobile.service.client, "complete", unexpected)
    rest = client.post("/api/app/v1/plan", json=request)
    assert rest.status_code == 200
    assert rest.json()["item"] is None
    assert rest.json()["source"] == "template"
    assert "今天已记录" in rest.json()["reason"]

    request["history"][0]["status"] = "cancelled"
    seen = []

    def complete(messages):
        seen.append(json.loads(messages[1]["content"])["facts"])
        return json.dumps({"stage_name": "适应期", "headline": "练习深蹲", "reason": "逐步练习。",
                           "item": {"exercise_id": "squat", "title": "徒手深蹲", "target_sets": 1,
                                    "target_reps": 6, "rest_seconds": 45}}, ensure_ascii=False), {}

    monkeypatch.setattr(mobile.service.client, "complete", complete)
    training = client.post("/api/app/v1/plan", json=request)
    assert training.status_code == 200
    assert training.json()["item"]["exercise_id"] == "squat"
    assert seen[0]["history_summary"]["completed_training_days_this_week"] == 0
    assert "history" not in seen[0]


def test_weekly_day_goal_uses_distinct_dates(client, fixture_data, monkeypatch):
    base = fixture_data["summary_request"]["session"]
    one = json.loads(json.dumps(base))
    two = json.loads(json.dumps(base))
    one["session_id"] = "day-one"
    one["finished_at"] = "2026-10-01T18:00:00+08:00"
    two["session_id"] = "day-two"
    two["finished_at"] = "2026-10-02T18:00:00+08:00"
    request = json.loads(json.dumps(fixture_data["plan_request"]))
    request["local_date"] = "2026-10-03"
    request["history"] = [one, two]

    def unexpected(_):
        raise AssertionError("the weekly target should be evaluated before calling the model")

    monkeypatch.setattr(mobile.service.client, "complete", unexpected)
    result = client.post("/api/app/v1/plan", json=request)
    assert result.status_code == 200
    assert result.json()["item"] is None
    assert "本周已记录 2 个训练日" in result.json()["reason"]


def test_nutrition_limited_does_not_call_model(client, fixture_data, monkeypatch):
    def unexpected(_):
        raise AssertionError("special diet must not be sent to a model without details")

    monkeypatch.setattr(mobile.service.client, "complete", unexpected)
    limited = client.post("/api/app/v1/nutrition", json=fixture_data["nutrition_request"])
    assert limited.status_code == 200
    assert limited.json()["source"] == "template"
    assert "无法给出个体化" in limited.json()["body"]


def test_summary_is_idempotent_and_does_not_invent_quality(client, fixture_data, monkeypatch):
    calls = []

    def complete(messages):
        calls.append(json.loads(messages[1]["content"]))
        return json.dumps({"highlights": ["counts_are_device_estimates"],
                           "next_session_suggestion": "repeat_without_progression"}), {}

    monkeypatch.setattr(mobile.service.client, "complete", complete)
    request = fixture_data["summary_request"]
    first = client.post("/api/app/v1/sessions/summary", json=request)
    second = client.post("/api/app/v1/sessions/summary", json=request)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(calls) == 1
    body = first.json()
    assert body["facts"]["quality_available"] is False
    assert body["quality_trend"] is None
    assert body["main_error_code"] is None
    assert body["next_plan_changed"] is False
    assert "无法评价姿势" in body["agent_summary"]
    assert "installation_id" not in calls[0]["facts"]
    conflicting = json.loads(json.dumps(request))
    conflicting["session"]["exercises"][0]["completed_reps"] = 7
    response = client.post("/api/app/v1/sessions/summary", json=conflicting)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SESSION_CONFLICT"
    deleted = client.post("/api/app/v1/data/delete", json=fixture_data["delete_request"])
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}


def test_interrupted_session_cannot_receive_progression_suggestion(client, fixture_data, monkeypatch):
    request = json.loads(json.dumps(fixture_data["summary_request"]))
    request["session"]["session_id"] = "interrupted-001"
    request["session"]["status"] = "interrupted"
    request["session"]["exercises"][0]["completed_sets"] = 0
    request["session"]["exercises"][0]["completed_reps"] = 0
    calls = []

    def complete(messages):
        calls.append(1)
        if len(calls) == 1:
            suggestion = "repeat_without_progression"
        else:
            suggestion = "review_capture_setup"
        return json.dumps({"highlights": [], "next_session_suggestion": suggestion}), {}

    monkeypatch.setattr(mobile.service.client, "complete", complete)
    response = client.post("/api/app/v1/sessions/summary", json=request)
    assert response.status_code == 200
    assert len(calls) == 2
    assert "异常中断" in response.json()["agent_summary"]
    assert "相机" in response.json()["agent_summary"]


def test_health_field_is_rejected_and_no_model_is_false_503(client, fixture_data, monkeypatch):
    request = json.loads(json.dumps(fixture_data["plan_request"]))
    request["profile"]["has_current_discomfort"] = False
    invalid = client.post("/api/app/v1/plan", json=request)
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "INVALID_REQUEST"

    def missing(_):
        raise mobile.ConfigurationError("missing")

    monkeypatch.setattr(mobile.service.client, "complete", missing)
    unavailable = client.post("/api/app/v1/plan", json=fixture_data["plan_request"])
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "MODEL_NOT_CONFIGURED"


def test_weekly_progress_counts_distinct_days_and_falls_back_without_model(client, fixture_data, monkeypatch):
    one = json.loads(json.dumps(fixture_data["summary_request"]["session"]))
    two = json.loads(json.dumps(one))
    interrupted = json.loads(json.dumps(one))
    one["session_id"] = "one"
    two["session_id"] = "two"
    interrupted["session_id"] = "interrupted"
    interrupted["status"] = "interrupted"
    request = {"profile": fixture_data["profile"], "history": [one, two, interrupted],
               "local_date": "2026-10-03"}

    def unavailable(_):
        raise mobile.ConfigurationError("no model configured")

    monkeypatch.setattr(mobile.service.client, "complete", unavailable)
    response = client.post("/api/app/v1/progress/weekly", json=request)
    assert response.status_code == 200
    body = response.json()
    assert body["completed_training_days"] == 1
    assert body["completed_sessions"] == 2
    assert body["total_reps"] == 12
    assert body["interrupted_sessions"] == 1
    assert body["quality_available"] is False
    assert body["source"] == "template"


def test_weekly_progress_agent_can_choose_bounded_advice(client, fixture_data, monkeypatch):
    record = json.loads(json.dumps(fixture_data["summary_request"]["session"]))
    request = {"profile": fixture_data["profile"], "history": [record], "local_date": "2026-10-03"}

    def complete(_):
        return json.dumps({"next_step": "review_schedule"}), {}

    monkeypatch.setattr(mobile.service.client, "complete", complete)
    response = client.post("/api/app/v1/progress/weekly", json=request)
    assert response.status_code == 200
    assert response.json()["source"] == "agent"
    assert "检查接下来" in response.json()["next_step"]

"""Completed-set contracts and synthetic regressions, not model accuracy tests."""
from copy import deepcopy
import math
import time

import pytest
from fastapi.testclient import TestClient

from main import app
from api.routes import manager
from perception.agent import PerceptionAgent, PerceptionSession
from perception.sets import analyze_set, capture_frame, MAX_SET_FRAMES
from pipeline.clock import now, observation_time
from .test_recognition_regressions import curl_pose
from .test_ab_chain import FakeModel, FakePerceptionModel


def frames(count=150):
    return [{"timestamp":1700000000000+i*1000/30,
             "landmarks":curl_pose(115+55*math.cos(i/15)), "client_probs":{"curl-stand":.99}}
            for i in range(count)]


def test_completed_set_replays_confirmed_action_from_start():
    source = frames()
    before = deepcopy(source)
    result, snapshots = analyze_set(source, "synthetic-set")
    assert source == before
    assert result["feedback_scope"] == "completed_set"
    assert result["resolved_segment_frames"] > result["online_confirmed_frames"]
    segment = result["segments"][0]
    assert segment["exercise"] == "bicep_curl"
    assert segment["frames"] == len(source)
    assert segment["repetitions"] >= 1
    assert segment["action_report"]["repetition"] == segment["repetitions"]
    assert snapshots[0]["action_report"]["kinematics"]["set_summary"]["repetitions"] == segment["repetitions"]


def test_static_bent_arms_remain_unresolved_in_batch():
    source = frames(60)
    for item in source:
        item["landmarks"] = curl_pose(80)
    result, snapshots = analyze_set(source, "static-set")
    assert result["status"] == "awaiting_evidence"
    assert not result["segments"] and not snapshots


def test_tracking_loss_separates_segments():
    source = frames(90)
    source.append({"timestamp":source[-1]["timestamp"]+50, "landmarks":[]})
    second = frames(90)
    for item in second:
        item["timestamp"] += 5000
    result, _ = analyze_set(source+second, "lost-set")
    assert len(result["segments"]) == 2
    assert all(segment["frames"] == 90 for segment in result["segments"])


def test_observation_clock_is_scoped_and_restored(monkeypatch):
    monkeypatch.setattr("time.time", lambda:100)
    assert now() == 100
    with observation_time(1):
        assert now() == 1
        with observation_time(2):
            assert now() == 2
        assert now() == 1
    assert now() == 100


def test_capture_is_bounded_and_reports_loss():
    session = PerceptionSession()
    payload = frames(1)[0]
    for _ in range(MAX_SET_FRAMES+2):
        capture_frame(session, payload)
    assert len(session.frame_buffer) == MAX_SET_FRAMES
    assert session.buffer_dropped == 2
    session.reset(clear_buffer=False)
    assert len(session.frame_buffer) == MAX_SET_FRAMES
    session.reset()
    assert not session.frame_buffer


def test_malformed_capture_does_not_poison_buffer():
    session = PerceptionSession()
    capture_frame(session, {"timestamp":1,"landmarks":[{"x":float("nan"),"y":.5}]})
    assert not session.frame_buffer and session.buffer_rejected == 1


def test_stop_then_finish_without_model_and_duplicate_finish(monkeypatch):
    session = PerceptionSession()
    for payload in frames(90):
        capture_frame(session, payload)
    monkeypatch.setitem(manager.recent_sessions, "archived-set", (time.monotonic(), session))
    client = TestClient(app)
    reply = client.post("/api/agent-a/sessions/archived-set/finish-set", json={})
    assert reply.status_code == 200, reply.text
    assert reply.json()["segments"]
    assert not session.frame_buffer
    assert client.post("/api/agent-a/sessions/archived-set/finish-set", json={}).status_code == 409
    previous = client.post("/api/agent-a/sessions/archived-set/review-set", json={})
    assert previous.json()["set_id"] == reply.json()["set_id"]


def test_completed_set_agents_use_skills_once_and_preserve_counts(monkeypatch):
    import api.set_routes as routes
    from app.agents import AgentService
    model = FakeModel()
    monkeypatch.setattr(routes, "PerceptionAgent", lambda:PerceptionAgent(FakePerceptionModel()))
    monkeypatch.setattr(routes, "run", AgentService(model).run)
    session = PerceptionSession()
    for payload in frames():
        capture_frame(session, payload)
    monkeypatch.setitem(manager.perception_sessions, "mock-agent-set", session)
    client = TestClient(app)
    result = client.post("/api/agent-a/sessions/mock-agent-set/finish-set", json={"include_agents":True})
    assert result.status_code == 200, result.text
    segment = result.json()["segments"][0]
    assert "analysis" in segment
    assert segment["analysis"]["agent"]["specialist"] == "curl_form"
    assert segment["action_report"]["repetition"] == segment["repetitions"]
    assert "set_summary" in model.calls[0][1]["content"]
    repeat = client.post("/api/agent-a/sessions/mock-agent-set/review-set", json={"include_agents":True})
    assert repeat.status_code == 200
    assert len(model.calls) == 1


def test_failed_local_analysis_restores_capture(monkeypatch):
    import api.set_routes as routes
    session = PerceptionSession()
    for payload in frames(5):
        capture_frame(session, payload)
    monkeypatch.setitem(manager.perception_sessions, "failed-set", session)
    def failure(*args):
        raise RuntimeError("explicit mock failure")
    monkeypatch.setattr(routes, "local_analysis", failure)
    reply = TestClient(app, raise_server_exceptions=False).post("/api/agent-a/sessions/failed-set/finish-set", json={})
    assert reply.status_code == 500
    assert len(session.frame_buffer) == 5
    assert not session.set_busy


def test_imported_set_invalid_landmark_shape_rejected():
    reply = TestClient(app).post("/api/agent-a/analyze-set", json={"session_id":"bad", "frames":[{"timestamp":1, "landmarks":[{"x":.5,"y":.5}]}]})
    assert reply.status_code == 422


def test_websocket_capture_survives_disconnect_and_finishes(monkeypatch):
    monkeypatch.setattr(manager, "should_rate_limit", lambda client_id:False)
    client = TestClient(app)
    with client.websocket_connect("/api/ws/pose/buffer-chain") as socket:
        for payload in frames(90):
            socket.send_json(payload)
            response = socket.receive_json()
        assert response["capture"]["frames"] == 90
    reply = client.post("/api/agent-a/sessions/buffer-chain/finish-set", json={})
    assert reply.status_code == 200, reply.text
    assert reply.json()["retained_frames"] == 90
    assert reply.json()["segments"][0]["exercise"] == "bicep_curl"

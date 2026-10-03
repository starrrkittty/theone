"""Deterministic regression coverage, never real model quality evidence."""
from copy import deepcopy
import json
import time

import pytest
from fastapi.testclient import TestClient

from main import app
from perception.agent import PerceptionAgent, PerceptionSession
from perception.evidence import evidence_packet, review_profile, evidence_changed
from kinematics.fitting import SkeletonFitter
from kinematics.urdf_loader import parse_urdf, UrdfError
from schemas.action_report import ActionReport
from app.prompt_context import model_context
from .test_recognition_regressions import curl_pose


class FakeModel:
    def __init__(self, decision="handoff"):
        self.messages = []
        self.decision = decision

    def complete(self, messages):
        self.messages.append(deepcopy(messages))
        return json.dumps({"tool":"finish", "decision":self.decision, "reason":"Explicit fake model",
                           "observation_request":"none"}), {"model":"fake", "usage":{"total_tokens":50}}


def ready_session():
    session = PerceptionSession()
    for index in range(30):
        pose = curl_pose(70 + index*3)
        points = [[p["x"],p["y"],p["z"],p["visibility"]] for p in pose]
        report = ActionReport(session_id="optimization-test", timestamp_ms=1700000000000+index*50,
                              recognition_status="confirmed", recognized_exercise="bicep_curl",
                              recognition_confidence=.95, pose_quality="good", camera_view="side")
        session.update(report, points)
    assert session.latest["action_report"]["perception_agent"]["handoff_allowed"]
    return session


def test_generated_urdf_comments_are_accepted():
    fitter = SkeletonFitter()
    pose = curl_pose(100)
    fitter.update([[p["x"],p["y"],p["z"],p["visibility"]] for p in pose], 1700000000000)
    assert "<!--" in fitter.xml
    assert "left_elbow_joint" in parse_urdf(fitter.xml).joints


@pytest.mark.parametrize("declaration", ["<!DOCTYPE robot>", '<!ENTITY x "test">'])
def test_unsafe_xml_declarations_rejected(declaration):
    with pytest.raises(UrdfError):
        parse_urdf(declaration+'<robot name="r"><link name="root"/></robot>')


def test_one_call_compact_agent_retains_measurements():
    session = ready_session()
    snapshot = session.snapshot()
    before = deepcopy(snapshot)
    model = FakeModel()
    result = PerceptionAgent(model).run(snapshot)
    assert snapshot == before
    assert result["perception_agent"]["handoff_allowed"]
    assert result["perception_agent"]["model_calls"] == 1
    packet = json.loads(model.messages[0][1]["content"])["evidence"]
    assert "left_elbow_joint" in packet["joint_states"]
    assert "left_knee_joint" not in packet["joint_states"]
    assert "origin_xyz" not in packet["joint_definitions"]["left_elbow_joint"]
    assert len(model.messages[0][1]["content"]) < len(json.dumps(snapshot["action_report"]))


def test_model_cannot_override_failed_gate():
    snapshot = ready_session().snapshot()
    snapshot["action_report"]["recognition_status"] = "candidate"
    result = PerceptionAgent(FakeModel()).run(snapshot)
    assert not result["perception_agent"]["handoff_allowed"]
    assert result["perception_agent"]["decision"] == "observe"


def test_profile_deadband_and_quality_changes():
    snapshot = ready_session().snapshot()
    gate = PerceptionSession.policy(snapshot)
    old = review_profile(snapshot, gate)
    changed = deepcopy(snapshot)
    changed["motion"]["joints"]["left_elbow_joint"]["low_rad"] += .001
    assert not evidence_changed(old, review_profile(changed, gate))
    changed["motion"]["joints"]["left_elbow_joint"]["low_rad"] += .3
    assert evidence_changed(old, review_profile(changed, gate))
    changed = deepcopy(snapshot)
    changed["action_report"]["camera_view"] = "front"
    assert evidence_changed(old, review_profile(changed, gate))


def test_cache_provenance_and_expiry():
    session = ready_session()
    snapshot = session.snapshot()
    result = PerceptionAgent(FakeModel()).run(snapshot)
    result["status"] = "completed"
    session.review_result = result
    session.review_baseline = snapshot["review_revision"]
    session.review_cached_at = time.monotonic()
    cached = session.cached_review(snapshot)
    assert cached["perception_agent"]["model_called"] is False
    assert cached["perception_agent"]["cache_hit"] is True
    assert cached["perception_agent"]["reused_from_timestamp_ms"] == result["action_report"]["timestamp_ms"]
    session.review_cached_at -= 46
    assert session.cached_review(snapshot) is None


def test_tracking_loss_and_gap_invalidate_cache_revision():
    session = ready_session()
    revision = session.review_revision
    report = ActionReport(session_id="optimization-test",timestamp_ms=1700000005000,
                          recognition_status="unknown")
    session.update(report, [])
    assert session.review_revision > revision
    assert session.latest["motion"]["joints"] == {}
    assert not session.latest["action_report"]["perception_agent"]["handoff_allowed"]


def test_b_context_projection_does_not_modify_export():
    context = {"agent_a_observations":{"kinematics":{"structure":{"raw":"large"}, "coordinate_units":"estimated_meters", "limitations":["uncalibrated"]},
              "perception_agent":{"trace":[{"raw":"large"}], "handoff_allowed":True},
              "metrics":{"joint_angles":{"left_elbow":90},"hold_seconds":5}}}
    before = deepcopy(context)
    projected = model_context("movement",context)
    assert context == before
    assert "structure" not in projected["agent_a_observations"]["kinematics"]
    assert projected["agent_a_observations"]["kinematics"]["limitations"] == ["uncalibrated"]
    assert "trace" not in projected["agent_a_observations"]["perception_agent"]


def test_duplicate_connection_cannot_replace_session():
    from starlette.websockets import WebSocketDisconnect
    from api.routes import manager
    client = TestClient(app)
    with client.websocket_connect("/api/ws/pose/ownership-test"):
        original = manager.perception_sessions["ownership-test"]
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/ws/pose/ownership-test"):
                pass
        assert manager.perception_sessions["ownership-test"] is original


@pytest.mark.parametrize("delta", [-50, 1000])
def test_stream_discontinuity_resets_entire_measured_pipeline(delta):
    from perception.pipeline import process_pose_frame
    from reporting.builder import ActionReportBuilder
    from state_machine.manager import FormManager
    session = PerceptionSession()
    manager = FormManager()
    builder = ActionReportBuilder("discontinuity")
    process_pose_frame(manager, builder, session, {"timestamp":1700000000000, "landmarks":curl_pose(80)})
    generation = session.generation
    process_pose_frame(manager, builder, session, {"timestamp":1700000000000+delta, "landmarks":curl_pose(80)})
    assert session.generation == generation+1
    assert manager._frames_processed == 1
    assert len(manager._temporal.samples) == 1


def test_cached_resources_reload_on_file_change(monkeypatch):
    from types import SimpleNamespace
    import app.agent_tools as module
    class Resource:
        text = "old"
        modified = 1
        reads = 0
        def __str__(self):
            return "explicit-fake-resource.md"
        def stat(self):
            return SimpleNamespace(st_mtime_ns=self.modified, st_size=len(self.text))
        def read_text(self, **kwargs):
            self.reads += 1
            return self.text
    path = Resource()
    monkeypatch.setattr(module, "Path", lambda name:path)
    module._file_content.cache_clear()
    assert module.read_cached(path) == "old"
    assert module.read_cached(path) == "old"
    assert path.reads == 1
    path.text, path.modified = "updated content", 2
    assert module.read_cached(path) == "updated content"
    assert path.reads == 2
    module._file_content.cache_clear()


def test_model_capacity_released_after_transport_error(monkeypatch):
    from threading import BoundedSemaphore
    from urllib.error import URLError
    import app.model_client as module
    semaphore = BoundedSemaphore(1)
    monkeypatch.setattr(module, "_MODEL_CAPACITY", semaphore)
    monkeypatch.setattr(module, "configuration", lambda: {"api_key":"fake", "base_url":"http://localhost:9999", "model":"fake", "json_mode":True, "timeout_seconds":1})
    def failing_transport(*args, **kwargs):
        raise URLError("explicit mock failure")
    monkeypatch.setattr(module, "urlopen", failing_transport)
    with pytest.raises(module.ModelError):
        module.ModelClient().complete([{"role":"user", "content":"{}"}])
    assert semaphore.acquire(blocking=False)
    semaphore.release()


def test_reset_during_a_review_cannot_handoff(monkeypatch):
    from types import SimpleNamespace
    import api.perception_routes as routes
    from api.routes import manager
    session = ready_session()
    monkeypatch.setitem(manager.perception_sessions, "optimization-test", session)
    monkeypatch.setattr(routes, "ModelClient", lambda:SimpleNamespace(status=lambda:{"configured":True}))
    def reset_during_review(snapshot):
        result = PerceptionAgent(FakeModel()).run(snapshot)
        session.reset()
        return result
    monkeypatch.setattr(routes, "PerceptionAgent", lambda:SimpleNamespace(run=reset_during_review))
    reply = TestClient(app).post("/api/agent-a/sessions/optimization-test/review")
    assert reply.status_code == 200
    assert reply.json()["status"] == "stale"
    assert not reply.json()["perception_agent"]["handoff_allowed"]
    assert not session.reviewing


def test_reset_during_b_inference_marks_feedback_historical(monkeypatch):
    import api.coach_bridge as bridge
    from api.routes import manager
    session = ready_session()
    report = session.snapshot()["action_report"]
    monkeypatch.setitem(manager.perception_sessions, "optimization-test", session)
    async def reviewed(client_id):
        return {"status":"completed", "action_report":report, "perception_agent":{"handoff_allowed":True}}
    def reset_during_inference(*args):
        session.reset()
        return {"status":"explicit_fake"}
    monkeypatch.setattr(bridge, "review_session", reviewed)
    monkeypatch.setattr(bridge, "run", reset_during_inference)
    reply = TestClient(app).post("/api/agent-a/coach", json={"action_report":report})
    assert reply.status_code == 200, reply.text
    assert reply.json()["status"] == "historical_feedback"
    assert reply.json()["feedback_scope"] == "historical"
    assert not session.coaching

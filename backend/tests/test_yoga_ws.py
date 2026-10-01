"""Tests for the YogaManager and the /api/ws/yoga WebSocket endpoint."""

import pytest

import pipeline.hold_timer as hold_timer_module
from state_machine.yoga_manager import YogaManager


def _skeleton(joints: dict[int, tuple[float, float]]) -> list[dict]:
    lms = [{"x": 0.5, "y": 0.5, "z": 0.0, "visibility": 0.9} for _ in range(33)]
    for idx, (x, y) in joints.items():
        lms[idx] = {"x": x, "y": y, "z": 0.0, "visibility": 0.95}
    return lms


# A correct Tree pose (standing on the left leg, right foot lifted).
TREE_OK = _skeleton({
    11: (0.42, 0.25), 12: (0.58, 0.25), 23: (0.45, 0.55), 24: (0.55, 0.55),
    25: (0.45, 0.75), 26: (0.64, 0.64), 27: (0.45, 0.95), 28: (0.47, 0.72),
})
# A correct Mountain pose.
MOUNTAIN_OK = _skeleton({
    11: (0.42, 0.25), 12: (0.58, 0.25), 13: (0.40, 0.40), 14: (0.60, 0.40),
    15: (0.40, 0.55), 16: (0.60, 0.55), 23: (0.45, 0.55), 24: (0.55, 0.55),
    25: (0.45, 0.75), 26: (0.55, 0.75), 27: (0.45, 0.95), 28: (0.55, 0.95),
})


# --------------------------------------------------------------------------- #
# YogaManager unit tests (time-controlled)
# --------------------------------------------------------------------------- #

def test_manager_idle_without_pose():
    mgr = YogaManager()
    state = mgr.process_frame(TREE_OK)
    assert state.state == "idle"
    assert state.current_pose is None


def test_manager_unknown_pose_rejected():
    mgr = YogaManager()
    assert mgr.set_pose("not_a_pose") is False
    assert mgr.set_pose("tree") is True


def test_manager_hold_progresses_and_completes(monkeypatch):
    mgr = YogaManager()
    mgr.set_pose("tree")  # target_hold_seconds = 20.0

    now = 1000.0
    last = None
    completed_count = 0
    progresses = []
    # 25s of correct holding at 20 fps → must cross the 20s target once.
    for _ in range(500):
        now += 0.05
        monkeypatch.setattr(hold_timer_module.time, "time", lambda t=now: t)
        last = mgr.process_frame(TREE_OK)
        progresses.append(last.hold_progress)
        completed_count += int(last.just_completed)

    assert last.is_in_pose
    assert last.current_pose == "tree"
    assert last.hold_complete
    assert completed_count == 1
    assert all(b >= a for a, b in zip(progresses, progresses[1:]))  # monotonic


def test_manager_pose_switch_resets_hold(monkeypatch):
    mgr = YogaManager()
    mgr.set_pose("tree")

    now = 1000.0
    for _ in range(40):  # build up ~2s of tree hold
        now += 0.05
        monkeypatch.setattr(hold_timer_module.time, "time", lambda t=now: t)
        state = mgr.process_frame(TREE_OK)
    assert state.hold_seconds > 1.0

    # Switching to a different pose must start a fresh hold from zero.
    mgr.set_pose("mountain")
    now += 0.05
    monkeypatch.setattr(hold_timer_module.time, "time", lambda t=now: t)
    state = mgr.process_frame(MOUNTAIN_OK)
    assert state.current_pose == "mountain"
    assert state.hold_seconds < 0.1


# --------------------------------------------------------------------------- #
# WebSocket + REST endpoint tests (require httpx for FastAPI TestClient)
# --------------------------------------------------------------------------- #

def _client():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


def test_get_yoga_poses_endpoint():
    client = _client()
    resp = client.get("/api/yoga/poses")
    assert resp.status_code == 200
    poses = resp.json()["poses"]
    assert len(poses) == 8
    labels = {p["label"] for p in poses}
    assert "tree" in labels and "downward_dog" in labels


def test_ws_yoga_hold_increases_and_switches():
    client = _client()
    with client.websocket_connect("/api/ws/yoga/testclient") as ws:
        first_hold = None
        for _ in range(5):
            ws.send_json({"landmarks": TREE_OK, "timestamp": 1, "pose": "tree"})
            resp = ws.receive_json()
            assert resp["current_pose"] == "tree"
            assert resp["is_in_pose"] is True
            assert resp["hold_target_seconds"] == 20.0
            if first_hold is None:
                first_hold = resp["hold_seconds"]
        assert resp["hold_seconds"] >= first_hold  # time accumulates

        # Switching the pose field mid-stream resets the hold + detector.
        ws.send_json({"landmarks": MOUNTAIN_OK, "timestamp": 2, "pose": "mountain"})
        resp = ws.receive_json()
        assert resp["current_pose"] == "mountain"
        assert resp["hold_seconds"] < first_hold + 1.0


def test_yoga_health_endpoint():
    client = _client()
    resp = client.get("/api/yoga/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert len(body["supported_poses"]) == 8


def test_root_advertises_yoga_mode():
    client = _client()
    modes = client.get("/").json()["modes"]
    assert modes["yoga"]["websocket"] == "/api/ws/yoga/{client_id}"
    assert modes["yoga"]["catalog"] == "/api/yoga/poses"


def test_ws_yoga_unknown_pose_reports_error():
    client = _client()
    with client.websocket_connect("/api/ws/yoga/testclient") as ws:
        ws.send_json({"landmarks": TREE_OK, "timestamp": 7, "pose": "not_a_pose"})
        resp = ws.receive_json()
        assert resp["state"] == "idle"
        assert resp["current_pose"] is None
        assert "Unknown pose" in resp["correction_message"]
        assert resp["timestamp"] == 7

        # A valid label afterwards still works — the connection stays usable.
        ws.send_json({"landmarks": TREE_OK, "timestamp": 8, "pose": "tree"})
        assert ws.receive_json()["current_pose"] == "tree"


def test_ws_yoga_rejects_invalid_client_id():
    client = _client()
    with pytest.raises(Exception):
        with client.websocket_connect("/api/ws/yoga/bad id!") as ws:
            ws.receive_json()

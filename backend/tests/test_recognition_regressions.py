import copy
import math
from types import SimpleNamespace

import numpy as np
import pytest

from exercises.base import ExerciseType
from pipeline.features import BodyFrame, FeatureExtractor
from recognition.external import parse_external_probabilities
from recognition.temporal import TemporalEvidence
from reporting.builder import ActionReportBuilder
from state_machine.manager import FormManager


def standing_pose():
    points = [{"x":0.5,"y":0.2,"z":0.,"visibility":0.95} for _ in range(33)]
    for indices, x in (((11,13,15,23,25,27),.43), ((12,14,16,24,26,28),.57)):
        for index, y in zip(indices, (.26,.42,.58,.56,.77,.98)):
            points[index]["x"], points[index]["y"] = x, y
    return points


def curl_pose(angle):
    points = standing_pose()
    for elbow, wrist in ((13,15),(14,16)):
        points[wrist]["x"] = points[elbow]["x"] + .16 * math.sin(math.radians(angle))
        points[wrist]["y"] = points[elbow]["y"] - .16 * math.cos(math.radians(angle))
    return points


def test_model_variants_are_merged_into_runtime_labels():
    evidence = parse_external_probabilities({"curl-stand":.50,"curl-seat":.35,"alt-stand":.10,"alt-seat":.05})
    assert evidence.top1 == "bicep_curl"
    assert evidence.top1_confidence == pytest.approx(.85)
    assert evidence.margin == pytest.approx(.70)


def test_static_bent_arms_are_not_confirmed_as_exercise(monkeypatch):
    manager = FormManager()
    for index in range(120):
        monkeypatch.setattr("time.time", lambda: 1000 + index / 30)
        state = manager.process_frame(curl_pose(80), {"curl-stand":.99})
        assert state.current_exercise is None


def test_real_elbow_motion_can_confirm_curl(monkeypatch):
    manager = FormManager()
    confirmed = []
    for index in range(150):
        monkeypatch.setattr("time.time", lambda: 1000 + index / 30)
        angle = 115 + 55 * math.cos(index / 15)
        state = manager.process_frame(curl_pose(angle), {"curl-stand":.99})
        confirmed.append(state.current_exercise)
    assert ExerciseType.BICEP_CURL in confirmed


def test_no_pose_clears_public_report_and_drops_stale_module(monkeypatch):
    manager = FormManager()
    manager._activate_module(ExerciseType.SQUAT, "test")
    monkeypatch.setattr("time.time", lambda: 1000.)
    first = manager.process_frame([])
    assert first.current_exercise is None and first.exercise_result is None
    monkeypatch.setattr("time.time", lambda: 1003.)
    manager.process_frame([])
    assert manager.active_module is None


def test_seated_curl_motion_is_not_overridden_by_static_bent_knees(monkeypatch):
    manager = FormManager()
    labels = []
    for index in range(150):
        monkeypatch.setattr("time.time", lambda:1000 + index/30)
        points = curl_pose(115 + 55*math.cos(index/15))
        for knee,ankle in ((25,27),(26,28)):
            points[knee]["x"] += .2
            points[knee]["y"] = .62
            points[ankle]["x"] += .2
            points[ankle]["y"] = .86
        labels.append(manager.process_frame(points,{"curl-seat":.99}).current_exercise)
    assert ExerciseType.BICEP_CURL in labels
    assert ExerciseType.SQUAT not in labels


def test_horizontal_detection_is_scale_invariant_and_rejects_missing_legs():
    xyz = np.array([[p["x"],p["y"],p["z"]] for p in standing_pose()])
    tiny = (xyz - xyz.mean(axis=0)) * .1 + .5
    assert not FeatureExtractor().extract(tiny, np.zeros(33), np.ones(33)).is_horizontal
    xyz[[11,12],:2] = [.2,.4]
    xyz[[27,28],:2] = [.8,.4]
    assert FeatureExtractor().extract(xyz, np.zeros(33), np.ones(33)).is_horizontal
    vis = np.ones(33); vis[[27,28]] = 0
    assert not FeatureExtractor().extract(xyz, np.zeros(33), vis).is_horizontal


def test_squat_gate_does_not_depend_on_frame_crop():
    manager = FormManager()
    frame = BodyFrame(coords=np.zeros((33,3)), angles={"left_knee":90,"right_knee":90,"torso_angle":20},hip_y=.25)
    assert manager._rule_based_exercise(frame)[0] == ExerciseType.SQUAT


def test_static_pushup_bottom_is_not_forearm_plank():
    manager = FormManager(); manager._is_stationary = True
    frame = BodyFrame(coords=np.zeros((33,3)),angles={"left_elbow":90,"right_elbow":90},is_horizontal=True,forearm_support=False)
    assert manager._rule_based_exercise(frame)[0] == ExerciseType.PUSHUP


def test_temporal_evidence_ignores_one_outlier():
    evidence = TemporalEvidence()
    for index in range(30):
        evidence.update(BodyFrame(coords=np.zeros((33,3)),angles={"left_elbow":80 if index != 10 else 160}), index / 30)
    assert not evidence.moving("left_elbow")


@pytest.mark.parametrize("mode,expected", [("alternating", True), ("synchronous", False), ("one_arm", False)])
def test_alternate_curl_requires_opposite_motion(mode, expected):
    evidence = TemporalEvidence()
    for index in range(40):
        left = 100 + 40 * math.sin(index / 8)
        right = 200 - left if mode == "alternating" else left if mode == "synchronous" else 100
        evidence.update(BodyFrame(coords=np.zeros((33,3)), angles={"left_elbow":left, "right_elbow":right}), index/30)
    assert evidence.supports("alternate_bicep_curl") is expected


@pytest.mark.parametrize("competing", ["left_shoulder", "left_knee", "raised_arm"])
def test_competing_motion_is_not_curl_evidence(competing):
    evidence = TemporalEvidence()
    for index in range(40):
        angles = {"left_elbow":100+index, "left_shoulder":0}
        angles[competing if competing != "raised_arm" else "left_shoulder"] = 90 if competing == "raised_arm" else index*2
        evidence.update(BodyFrame(coords=np.zeros((33,3)), angles=angles), index/30)
    assert not evidence.supports("bicep_curl")


def test_unilateral_knee_bend_is_not_bilateral_squat():
    evidence = TemporalEvidence()
    for index in range(40):
        evidence.update(BodyFrame(coords=np.zeros((33,3)), angles={"left_knee":170-index*2, "right_knee":170}), index/30)
    assert not evidence.supports("squat")


def test_tracking_decline_is_not_reported_as_fatigue():
    builder = ActionReportBuilder("test")
    state = SimpleNamespace(current_exercise=None,candidate_exercise=None,exercise_result=None,
                            form_confidence=.9,signal_quality="good",stable_violations=[],camera_view="unknown")
    for confidence in [.9]*5 + [.5]*5:
        state.form_confidence = confidence
        report, _ = builder.build(state, 1000)
    assert not report.agent_context.possible_fatigue


def test_aspect_ratio_correction_preserves_geometry():
    normal = curl_pose(90)
    wide = copy.deepcopy(normal)
    for point in wide:
        point["y"] *= 1.5
    first = FormManager(); second = FormManager()
    first.process_frame(normal, image_aspect_ratio=1)
    second.process_frame(wide, image_aspect_ratio=1.5)
    assert first._measured_angles["left_elbow"] == pytest.approx(second._measured_angles["left_elbow"], abs=.001)


def test_reappearing_static_person_does_not_inherit_filter_motion(monkeypatch):
    manager = FormManager()
    for index in range(100):
        monkeypatch.setattr("time.time", lambda:1000+index/30)
        manager.process_frame(curl_pose(115+55*math.cos(index/15)),{"curl-stand":.99})
    manager.process_frame([])
    for index in range(90):
        monkeypatch.setattr("time.time", lambda:1004+index/30)
        assert manager.process_frame(curl_pose(80),{"curl-stand":.99}).current_exercise is None

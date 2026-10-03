from config.settings import settings
from exercises.base import ExerciseType, JointName, landmarks_to_dict
from exercises.plank import PlankModule
from state_machine.manager import FormManager, SystemState


def _landmarks():
    points = [
        {"x": 0.5, "y": 0.5, "z": 0.0, "visibility": 0.95}
        for _ in range(33)
    ]
    coordinates = {
        11: (0.25, 0.40), 12: (0.25, 0.42),
        13: (0.35, 0.40), 14: (0.35, 0.42),
        15: (0.35, 0.52), 16: (0.35, 0.54),
        23: (0.52, 0.40), 24: (0.52, 0.42),
        27: (0.82, 0.40), 28: (0.82, 0.42),
    }
    for index, (x, y) in coordinates.items():
        points[index].update(x=x, y=y)
    return points


def test_forearm_plank_enters_hold_and_reports_alignment():
    module = PlankModule()
    result = module.process_frame(_landmarks())

    assert result.rep_phase == "hold"
    assert result.rep_count == 0
    assert result.is_valid
    assert result.hold_seconds >= 0.0
    assert result.angles is not None


def test_plank_flags_sagging_hips():
    module = PlankModule()
    points = _landmarks()
    points[23]["y"] = 0.53
    points[24]["y"] = 0.55
    result = module.check_form(landmarks_to_dict(points))

    assert "Hips sagging" in result.violations
    assert not result.is_valid


def test_stationary_plank_can_activate_specialist(monkeypatch):
    """Stationary detection must not block an isometric exercise."""
    manager = FormManager()
    monkeypatch.setattr(settings, "EXERCISE_SWITCH_MIN_FRAMES", 2)
    monkeypatch.setattr(settings, "EXERCISE_SWITCH_MIN_SECONDS", 0.0)

    for _ in range(2):
        manager._maybe_switch_exercise(
            ExerciseType.PLANK,
            0.9,
            "rule_gate",
            SystemState.STATIONARY,
            "good",
        )

    assert manager.current_exercise == ExerciseType.PLANK
    assert isinstance(manager.active_module, PlankModule)

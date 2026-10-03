"""Tests for the yoga HoldTimer (time-in-pose tracker with jitter debounce)."""

import pipeline.hold_timer as hold_timer_module
from pipeline.hold_timer import HoldTimer


def _feed(monkeypatch, timer, sequence, start=1000.0, dt=0.05):
    """Feed a sequence of is_in_pose booleans at `dt` spacing (default 20 fps).

    Returns the list of result dicts, one per frame.
    """
    now = start
    results = []
    for is_in_pose in sequence:
        now += dt
        monkeypatch.setattr(hold_timer_module.time, "time", lambda t=now: t)
        results.append(timer.update(is_in_pose))
    return results


def test_progress_rises_monotonically_while_in_pose(monkeypatch):
    timer = HoldTimer(target_seconds=1.0, debounce_frames=10)
    results = _feed(monkeypatch, timer, [True] * 30)  # 30 frames @ 0.05 = 1.5s
    progresses = [r["progress"] for r in results]

    assert all(b >= a for a, b in zip(progresses, progresses[1:]))  # non-decreasing
    assert progresses[5] > progresses[0]  # actually rising
    assert progresses[-1] == 1.0


def test_single_dropped_frame_within_debounce_does_not_reset(monkeypatch):
    timer = HoldTimer(target_seconds=2.0, debounce_frames=10)
    seq = [True] * 10 + [False] + [True] * 5
    results = _feed(monkeypatch, timer, seq)

    before_drop = results[9]["progress"]
    on_drop = results[10]["progress"]
    after_drop = results[11]["progress"]

    assert on_drop >= before_drop  # the dropped frame did not reset progress
    assert after_drop >= on_drop
    assert after_drop > 0.0


def test_complete_and_just_completed_fire_exactly_once(monkeypatch):
    timer = HoldTimer(target_seconds=0.5, debounce_frames=10)
    results = _feed(monkeypatch, timer, [True] * 30)

    just_completed_count = sum(1 for r in results if r["just_completed"])
    assert just_completed_count == 1

    completed_flags = [r["complete"] for r in results]
    first_complete = completed_flags.index(True)
    assert all(completed_flags[first_complete:])  # stays complete while held


def test_sustained_loss_past_debounce_resets(monkeypatch):
    timer = HoldTimer(target_seconds=2.0, debounce_frames=5)
    seq = [True] * 10 + [False] * 8  # 8 misses > 5 debounce → reset
    results = _feed(monkeypatch, timer, seq)

    assert results[-1]["progress"] == 0.0
    assert results[-1]["duration"] == 0.0
    assert results[-1]["complete"] is False


def test_in_pose_after_reset_starts_a_fresh_hold(monkeypatch):
    timer = HoldTimer(target_seconds=0.5, debounce_frames=3)
    seq = [True] * 12 + [False] * 6 + [True] * 12
    results = _feed(monkeypatch, timer, seq)

    just_completed_count = sum(1 for r in results if r["just_completed"])
    assert just_completed_count == 2  # completed once, reset, completed again

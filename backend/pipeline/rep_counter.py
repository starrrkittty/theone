"""
Rep counting via a simple Schmitt-trigger on the exercise's primary joint angle.

A rep is one full flex-extend cycle on that single angle:
  extend zone  ->  flex zone  ->  extend zone   == 1 rep

Hysteresis bands at each end (a configurable fraction of the upper-lower
range) prevent jitter from double-counting near the thresholds. A light EMA
smooths landmark noise without adding latency. No find_peaks, no
Savitzky-Golay, no global frame indices, no plateau finalizers — those were
the moving parts that kept rejecting reps in practice. This counter only
cares about the angle the exercise module hands it.

Public surface preserved (all callers in exercises/*.py and state_machine
keep working unchanged):
  - constructor: upper_threshold, lower_threshold, min_rep_duration,
    max_rep_duration, require_full_extension, smooth_window, polyorder,
    prominence, min_rep_frames
  - update(angle, left_angle, right_angle, form_violations, visibility)
    -> (RepPhase, rep_completed: bool)
  - record_violations(list), reset()
  - rep_count, partial_reps, phase, phase_str, last_rep, average_quality,
    smoothed_angle, velocity_dps
"""

from collections import deque
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Optional
import time
import math
from pipeline.clock import now as observation_now


class RepPhase(str, Enum):
    """Mechanical rep counter phase, semantic to angle direction.

    ECCENTRIC = angle decreasing (joint flexing).
    CONCENTRIC = angle increasing (joint extending).
    Each exercise module maps these to user-facing labels.
    """
    IDLE = "idle"
    READY = "setup"
    ECCENTRIC = "eccentric"
    CONCENTRIC = "concentric"
    HOLD = "hold"
    TRANSITION = "setup"


@dataclass
class RepQuality:
    form_score: float = 1.0
    depth_score: float = 1.0
    tempo_score: float = 1.0
    symmetry_score: float = 1.0

    @property
    def overall_score(self) -> float:
        return (
            self.form_score * 0.4
            + self.depth_score * 0.3
            + self.tempo_score * 0.15
            + self.symmetry_score * 0.15
        )


@dataclass
class RepData:
    rep_number: int
    quality: RepQuality
    duration_seconds: float
    min_angle: float
    max_angle: float
    timestamp: float = field(default_factory=observation_now)
    observation_gap_ms: float = 0.0


# Hysteresis band depth as a fraction of (upper - lower). 0.40 means the
# extend zone covers the top 40% and the flex zone covers the bottom 40%;
# the middle 20% is the dead zone. Wide bands let partial-range reps count
# while still demanding a clear flex-extend cycle to trip both edges.
_BAND_RATIO = 0.40

# Minimum ROM as a fraction of (upper - lower). 0.25 keeps shallow but real
# reps countable while rejecting jitter that never crosses both bands.
_MIN_ROM_RATIO = 0.25

# Light EMA on the raw angle. 0.45 keeps reaction within ~2 frames at 20fps.
_EMA_DECAY = 0.45

# Velocity thresholds (degrees / second) for phase output. Velocity itself
# is smoothed by an EMA before comparison so single-frame jitter doesn't
# flip the phase between hold/eccentric/concentric.
_VELOCITY_HOLD_THRESHOLD = 12.0
_VELOCITY_DIR_THRESHOLD = 6.0
_VELOCITY_EMA_DECAY = 0.6

# Stillness check window: if the smoothed angle's peak-to-peak range over
# the last N frames is below this many degrees, force a HOLD output even
# if instantaneous velocity briefly spikes from landmark jitter.
_STILL_WINDOW_FRAMES = 10
_STILL_RANGE_DEGREES = 12.0

# Minimum visibility for a rep to count. Set low enough that transient
# occlusions don't kill reps but high enough that completely unreliable
# frames are rejected.
_VISIBILITY_REP_MIN = 0.3


class HysteresisRepCounter:
    """Schmitt-trigger rep counter on a single primary angle.

    States visited in order for one rep:
        EXTEND zone  ->  (between)  ->  FLEX zone  ->  (between)  ->  EXTEND zone

    The flex zone is angle <= lower_threshold + band_depth.
    The extend zone is angle >= upper_threshold - band_depth.
    Anything in between leaves the state unchanged (the dead zone).

    A rep is finalized at the moment the angle re-enters the extend zone after
    having been in the flex zone. Min/max angles within the rep are tracked
    from the smoothed signal so quality reflects the user's actual ROM.
    """

    def __init__(
        self,
        upper_threshold: float,
        lower_threshold: float,
        min_rep_duration: float = 0.4,
        max_rep_duration: float = 10.0,
        require_full_extension: bool = False,
        *,
        # Legacy kwargs preserved so existing call sites don't break. Not used
        # by the simple Schmitt-trigger algorithm — all are accepted silently.
        smooth_window: int = 9,
        polyorder: int = 3,
        prominence: float = 25.0,
        min_rep_frames: int = 8,
        max_observation_gap_seconds: float = 0.5,
    ):
        self.upper_threshold = float(upper_threshold)
        self.lower_threshold = float(lower_threshold)
        self.min_rep_duration = float(min_rep_duration)
        self.max_rep_duration = float(max_rep_duration)
        self.require_full_extension = bool(require_full_extension)
        self.max_observation_gap_seconds = float(max_observation_gap_seconds)

        # Legacy kwargs kept on the instance for callers that read them.
        self.smooth_window = int(smooth_window)
        self.polyorder = int(polyorder)
        self.prominence = float(prominence)
        self.min_rep_frames = int(min_rep_frames)

        rng = max(1.0, self.upper_threshold - self.lower_threshold)
        band = _BAND_RATIO * rng
        # Zone thresholds.
        self._flex_zone_max = self.lower_threshold + band     # angle <= this -> flex zone
        self._extend_zone_min = self.upper_threshold - band   # angle >= this -> extend zone
        # Minimum ROM to consider the cycle a real rep.
        self._min_rom = _MIN_ROM_RATIO * rng

        self._reset_state()

    def _reset_state(self) -> None:
        self._ema_angle: Optional[float] = None
        if hasattr(self, "_recent_smoothed"):
            self._recent_smoothed.clear()
        self._has_seen_extend: bool = False
        self._in_flex_phase: bool = False
        self._flex_start_time: Optional[float] = None
        self._cycle_start_time: Optional[float] = None
        self.rejected_cycles: list[dict] = []
        self.uncertain_cycles: list[dict] = []
        self.uncertain_cycle_count = 0
        self.accepted_cycles: list[dict] = []
        self._unobserved_since = None
        self._cycle_gap_ms = 0.0
        self._gap_expired = False
        self._flex_min_angle: float = 180.0
        self._flex_min_visibility: float = 1.0
        self._extend_max_angle: float = 0.0
        self._last_smoothed: Optional[float] = None
        self._last_update_time: Optional[float] = None

        self._phase: RepPhase = RepPhase.IDLE
        self._rep_count: int = 0
        self._partial_rep_count: int = 0
        self._reps: list[RepData] = []
        self._form_violations: list[str] = []
        self._left_angle: float = 0.0
        self._right_angle: float = 0.0
        self._velocity_dps: float = 0.0
        self._velocity_ema: float = 0.0
        self._recent_smoothed: deque = deque(maxlen=_STILL_WINDOW_FRAMES)

    def update(
        self,
        angle: float,
        left_angle: Optional[float] = None,
        right_angle: Optional[float] = None,
        form_violations: Optional[list[str]] = None,
        visibility: Optional[float] = None,
    ) -> tuple[RepPhase, bool]:
        now = observation_now()
        a = float(angle)
        if self._last_update_time is not None and now <= self._last_update_time:
            return self._phase, False
        if not math.isfinite(a) or not 0 <= a <= 180 or (visibility is not None and (not math.isfinite(visibility) or visibility < _VISIBILITY_REP_MIN)):
            self.mark_unobserved("angle_or_visibility_unreliable")
            return self._phase, False
        if self._last_update_time is not None and now-self._last_update_time > self.max_observation_gap_seconds:
            self._expire_observation_gap(now)
        elif self._unobserved_since is not None and self._last_update_time is not None:
            self._cycle_gap_ms = max(self._cycle_gap_ms, (now-self._last_update_time)*1000)
        self._unobserved_since = None
        self._gap_expired = False

        # Light EMA smoothing on the raw angle.
        if self._ema_angle is None:
            self._ema_angle = a
        else:
            elapsed = now-self._last_update_time if self._last_update_time is not None else .05
            d = _EMA_DECAY ** (elapsed/.05)
            self._ema_angle = d * self._ema_angle + (1.0 - d) * a
        smoothed = self._ema_angle

        # Velocity in degrees/second from smoothed signal, then EMA the
        # velocity so single-frame jitter doesn't flip the phase output.
        if self._last_update_time is not None and self._last_smoothed is not None:
            dt = max(now - self._last_update_time, 1e-3)
            self._velocity_dps = (smoothed - self._last_smoothed) / dt
            v = _VELOCITY_EMA_DECAY ** (dt/.05)
            self._velocity_ema = v * self._velocity_ema + (1.0 - v) * self._velocity_dps
        self._last_update_time = now
        self._last_smoothed = smoothed
        self._recent_smoothed.append(smoothed)

        if left_angle is not None:
            self._left_angle = float(left_angle)
        if right_angle is not None:
            self._right_angle = float(right_angle)
        if form_violations:
            self._form_violations.extend(form_violations)

        vis = float(visibility) if visibility is not None else 1.0

        # Classify zone with hysteresis.
        if smoothed >= self._extend_zone_min:
            zone = "extend"
        elif smoothed <= self._flex_zone_max:
            zone = "flex"
        else:
            zone = "between"

        rep_completed = False

        if zone == "extend":
            self._has_seen_extend = True
            self._extend_max_angle = max(self._extend_max_angle, smoothed)

            if self._in_flex_phase and self._flex_start_time is not None:
                # Rep cycle just closed: flex -> extend.
                duration = now - (self._cycle_start_time if self._cycle_start_time is not None else self._flex_start_time)
                peak = max(smoothed, self._extend_max_angle)
                trough = self._flex_min_angle

                if self._is_valid_rep(
                    duration=duration,
                    peak_value=peak,
                    trough_value=trough,
                    min_vis=self._flex_min_visibility,
                ):
                    self._rep_count += 1
                    self._reps.append(
                        RepData(
                            rep_number=self._rep_count,
                            quality=self._calculate_rep_quality(
                                duration, peak, trough
                            ),
                            duration_seconds=duration,
                            min_angle=trough,
                            max_angle=peak,
                            observation_gap_ms=self._cycle_gap_ms,
                        )
                    )
                    rep_completed = True
                    self.accepted_cycles.append({"rep_number":self._rep_count, "end_timestamp_ms":now*1000,
                        "duration_seconds":duration, "peak_angle":peak, "trough_angle":trough,
                        "minimum_visibility":self._flex_min_visibility, "observation_gap_ms":self._cycle_gap_ms,
                        "evidence":"observed_extend_flex_extend; predictions_do_not_trigger_transitions"})
                    self.accepted_cycles=self.accepted_cycles[-100:]
                else:
                    self._partial_rep_count += 1
                    self.rejected_cycles.append({"duration_seconds":duration,"peak_angle":peak,"trough_angle":trough,
                        "minimum_visibility":self._flex_min_visibility,
                        "reason":self._rejection_reason(duration,peak,trough,self._flex_min_visibility)})
                    self.rejected_cycles=self.rejected_cycles[-20:]

                # Reset for the next rep.
                self._in_flex_phase = False
                self._flex_start_time = None
                self._cycle_start_time = None
                self._flex_min_angle = 180.0
                self._flex_min_visibility = 1.0
                self._extend_max_angle = smoothed
                self._form_violations = []
                self._cycle_gap_ms = 0.0
            elif not self._in_flex_phase:
                self._cycle_start_time = None

        elif zone == "flex":
            # Only start tracking a rep once we've seen an extension first —
            # prevents a rep from being counted on initial setup if the user
            # starts with the joint already flexed.
            if self._has_seen_extend:
                if not self._in_flex_phase:
                    if self._cycle_start_time is None:
                        self._cycle_start_time=now
                    self._in_flex_phase = True
                    self._flex_start_time = now
                    self._flex_min_angle = smoothed
                    self._flex_min_visibility = vis
                else:
                    self._flex_min_angle = min(self._flex_min_angle, smoothed)
                    self._flex_min_visibility = min(self._flex_min_visibility, vis)

        else:
            if self._has_seen_extend and self._cycle_start_time is None:
                self._cycle_start_time=now
            # zone == "between"; if we're tracking a flex phase, keep updating
            # min angle in case the user dwells in the dead zone briefly.
            if self._in_flex_phase:
                self._flex_min_angle = min(self._flex_min_angle, smoothed)
                self._flex_min_visibility = min(self._flex_min_visibility, vis)

        # Phase output for the UI (uses smoothed velocity).
        self._phase = self._derive_phase(zone, self._velocity_ema)

        return self._phase, rep_completed

    def _expire_observation_gap(self, now):
        if self._gap_expired:
            return
        if self._cycle_start_time is not None or self._in_flex_phase:
            self.uncertain_cycle_count += 1
            self.uncertain_cycles.append({"reason":"occlusion_or_gap_interrupted_cycle",
                "start_timestamp_ms":(self._cycle_start_time if self._cycle_start_time is not None else self._flex_start_time if self._flex_start_time is not None else now)*1000,
                "last_observed_timestamp_ms":self._last_update_time*1000 if self._last_update_time is not None else None,
                "gap_ms":(now-self._last_update_time)*1000 if self._last_update_time is not None else None})
            self.uncertain_cycles=self.uncertain_cycles[-100:]
        self._has_seen_extend=False
        self._in_flex_phase=False
        self._cycle_start_time=self._flex_start_time=None
        self._flex_min_angle=180.0
        self._flex_min_visibility=1.0
        self._extend_max_angle=0.0
        self._ema_angle=self._last_smoothed=None
        self._velocity_ema=0.0
        self._recent_smoothed.clear()
        self._cycle_gap_ms=0.0
        self._gap_expired=True

    def mark_unobserved(self, reason="required_joints_occluded"):
        now=observation_now()
        if self._unobserved_since is None:
            self._unobserved_since=now
        if self._last_update_time is not None and now-self._last_update_time > self.max_observation_gap_seconds:
            self._expire_observation_gap(now)

    def evidence(self):
        return {"accepted_cycles":self.accepted_cycles, "rejected_cycles":self.rejected_cycles,
                "uncertain_cycles":self.uncertain_cycles, "uncertain_cycle_count":self.uncertain_cycle_count,
                "rules":{"flex_zone_max_deg":self._flex_zone_max,"extend_zone_min_deg":self._extend_zone_min,
                         "minimum_observed_range_deg":self._min_rom,"min_duration_seconds":self.min_rep_duration,
                         "max_duration_seconds":self.max_rep_duration,
                         "max_observation_gap_seconds":self.max_observation_gap_seconds,
                         "visibility_floor":_VISIBILITY_REP_MIN,
                         "threshold_status":"engineering_defaults_pending_independent_validation"}}

    def _derive_phase(self, zone: str, velocity_dps: float) -> RepPhase:
        # Stillness override: if the most recent frames have a tiny
        # peak-to-peak range, the body is effectively still — emit HOLD
        # regardless of any single-frame velocity spike. Only checks the
        # last few frames so a recent ascent doesn't poison the window.
        if len(self._recent_smoothed) >= 4:
            tail = list(self._recent_smoothed)[-5:]
            recent_range = max(tail) - min(tail)
            if recent_range <= _STILL_RANGE_DEGREES:
                return RepPhase.HOLD if self._has_seen_extend else RepPhase.READY
        if abs(velocity_dps) < _VELOCITY_HOLD_THRESHOLD:
            return RepPhase.HOLD if self._has_seen_extend else RepPhase.READY
        if velocity_dps < -_VELOCITY_DIR_THRESHOLD:
            return RepPhase.ECCENTRIC
        if velocity_dps > _VELOCITY_DIR_THRESHOLD:
            return RepPhase.CONCENTRIC
        return self._phase if self._phase != RepPhase.IDLE else RepPhase.READY

    def _is_valid_rep(
        self,
        *,
        duration: float,
        peak_value: float,
        trough_value: float,
        min_vis: float,
    ) -> bool:
        return self._rejection_reason(duration,peak_value,trough_value,min_vis) is None

    def _rejection_reason(self, duration, peak_value, trough_value, min_vis):
        if duration < self.min_rep_duration:
            return 'cycle_too_short'
        if duration > self.max_rep_duration:
            return 'cycle_too_long'
        rom = peak_value - trough_value
        if rom < self._min_rom:
            return 'insufficient_observed_range'
        if min_vis < _VISIBILITY_REP_MIN:
            return 'low_visibility'
        if self.require_full_extension:
            if peak_value < self.upper_threshold:
                return 'extension_threshold_not_reached'
            if trough_value > self.lower_threshold:
                return 'flexion_threshold_not_reached'
        return None

    def _calculate_rep_quality(
        self, duration: float, peak_value: float, trough_value: float
    ) -> RepQuality:
        form_score = max(0.0, 1.0 - len(self._form_violations) * 0.15)
        expected_range = self.upper_threshold - self.lower_threshold
        actual_range = peak_value - trough_value
        depth_score = min(1.0, actual_range / max(expected_range, 1.0))
        if 2.0 <= duration <= 4.0:
            tempo_score = 1.0
        elif duration < 1.0:
            tempo_score = 0.5
        elif duration > 6.0:
            tempo_score = 0.7
        else:
            tempo_score = 0.85
        if self._left_angle > 0 and self._right_angle > 0:
            symmetry_score = max(
                0.0, 1.0 - abs(self._left_angle - self._right_angle) / 30.0
            )
        else:
            symmetry_score = 1.0
        return RepQuality(
            form_score=form_score,
            depth_score=depth_score,
            tempo_score=tempo_score,
            symmetry_score=symmetry_score,
        )

    def record_violations(self, violations: list[str]) -> None:
        self._form_violations.extend(violations)

    def reset(self) -> None:
        self._reset_state()

    @property
    def rep_count(self) -> int:
        return self._rep_count

    @property
    def phase(self) -> RepPhase:
        return self._phase

    @property
    def phase_str(self) -> str:
        return self._phase.value

    @property
    def partial_reps(self) -> int:
        return self._partial_rep_count

    @property
    def average_quality(self) -> float:
        if not self._reps:
            return 0.0
        return sum(r.quality.overall_score for r in self._reps) / len(self._reps)

    @property
    def last_rep(self) -> Optional[RepData]:
        return self._reps[-1] if self._reps else None

    @property
    def smoothed_angle(self) -> float:
        return float(self._ema_angle) if self._ema_angle is not None else 0.0

    @property
    def velocity_dps(self) -> float:
        return self._velocity_dps


def _params_for(exercise_key: str) -> dict[str, Any]:
    """Look up REP_DETECTION overrides for an exercise key (legacy compat)."""
    try:
        from config.settings import settings
    except Exception:
        return {}
    cfg = getattr(settings, "REP_DETECTION", {}) or {}
    return dict(cfg.get(exercise_key, {}))


class ExerciseRepCounter:
    """Optional convenience factories — modules use exercises.base directly."""

    @staticmethod
    def create_bicep_curl_counter() -> HysteresisRepCounter:
        return HysteresisRepCounter(
            upper_threshold=150,
            lower_threshold=70,
            min_rep_duration=0.4,
            max_rep_duration=8.0,
            **_params_for("bicep_curl"),
        )

    @staticmethod
    def create_squat_counter() -> HysteresisRepCounter:
        return HysteresisRepCounter(
            upper_threshold=160,
            lower_threshold=100,
            min_rep_duration=0.5,
            max_rep_duration=10.0,
            **_params_for("squat"),
        )

    @staticmethod
    def create_pushup_counter() -> HysteresisRepCounter:
        return HysteresisRepCounter(
            upper_threshold=155,
            lower_threshold=100,
            min_rep_duration=0.4,
            max_rep_duration=8.0,
            **_params_for("pushup"),
        )

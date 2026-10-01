"""Convert the perception pipeline state into the stable Agent-A contract."""

from collections import deque
from dataclasses import asdict
from typing import Optional

from schemas.action_report import (
    ActionMetrics,
    ActionReport,
    AgentContext,
    CandidateExercise,
    RecognitionEvent,
    ViolationItem,
)


_DISPLAY_ZH = {
    "squat": "深蹲",
    "pushup": "俯卧撑",
    "plank": "平板支撑",
    "bicep_curl": "哑铃弯举",
    "alternate_bicep_curl": "交替哑铃弯举",
}


class ActionReportBuilder:
    """Maintain the small amount of temporal context needed by Agent B."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._last_exercise: Optional[str] = None
        self._violation_streaks: dict[str, int] = {}
        self._quality_history: deque[float] = deque(maxlen=10)

    def reset(self) -> None:
        self._last_exercise = None
        self._violation_streaks.clear()
        self._quality_history.clear()

    def build(self, state, timestamp_ms: float) -> tuple[ActionReport, Optional[RecognitionEvent]]:
        result = state.exercise_result
        current = state.current_exercise.value if state.current_exercise else None
        candidate = getattr(state, "candidate_exercise", None)
        candidate_name = candidate.value if candidate else None
        candidate_confidence = float(getattr(state, "candidate_confidence", 0.0))

        if current:
            recognition_status = "confirmed"
            exercise = current
            confidence = float(state.exercise_confidence)
        elif candidate_name:
            recognition_status = "candidate"
            exercise = "unknown"
            confidence = candidate_confidence
        else:
            recognition_status = "unknown"
            exercise = "unknown"
            confidence = 0.0

        candidates = []
        if candidate_name:
            candidates.append(CandidateExercise(
                exercise=candidate_name,
                confidence=candidate_confidence,
                source=state.exercise_source,
            ))

        violations = self._build_violations(state, result)
        max_streak = max((item.consecutive_frames for item in violations), default=0)

        quality = float(state.form_confidence)
        self._quality_history.append(quality)
        possible_fatigue = self._is_quality_declining()
        severity_high = any(item.severity == "high" for item in violations)
        should_coach = bool(violations) and (max_streak >= 2 or severity_high)

        if severity_high:
            priority = "safety"
        elif should_coach:
            priority = "form_correction"
        elif result and result.rep_count > 0 and not violations:
            priority = "encouragement"
        else:
            priority = "none"

        intent = "observe"
        if violations:
            intent = f"correct_{violations[0].type}"
        elif priority == "encouragement":
            intent = "reinforce_good_form"

        angles = {}
        if result and result.angles:
            angles = {
                key: round(float(value), 2)
                for key, value in asdict(result.angles).items()
            }

        report = ActionReport(
            session_id=self.session_id,
            timestamp_ms=timestamp_ms,
            recognition_status=recognition_status,
            recognized_exercise=exercise,
            recognition_confidence=max(0.0, min(1.0, confidence)),
            candidate_exercises=candidates,
            specialist=f"{exercise}_specialist" if current else None,
            phase=result.rep_phase if result else "idle",
            repetition=result.rep_count if result else 0,
            pose_quality=self._pose_quality(state.signal_quality),
            camera_view=state.camera_view,
            metrics=ActionMetrics(
                joint_angles=angles,
                hold_seconds=float(getattr(result, "hold_seconds", 0.0)) if result else 0.0,
                rep_quality=result.rep_quality if result else None,
                partial_reps=result.partial_reps if result else 0,
            ),
            violations=violations,
            agent_context=AgentContext(
                should_coach_now=should_coach,
                priority=priority,
                recommended_intent=intent,
                repeated_error_count=max_streak,
                possible_fatigue=possible_fatigue,
            ),
        )

        event = self._recognition_event(current, confidence, timestamp_ms)
        return report, event

    def _build_violations(self, state, result) -> list[ViolationItem]:
        stable = list(state.stable_violations or [])
        active_codes: set[str] = set()
        items: list[ViolationItem] = []

        if stable:
            for violation in stable:
                code = violation.code
                active_codes.add(code)
                streak = self._violation_streaks.get(code, 0) + 1
                self._violation_streaks[code] = streak
                items.append(ViolationItem(
                    type=code,
                    message=violation.message,
                    severity="high" if violation.severity == "red" else "medium",
                    confidence=0.9 if violation.severity == "red" else 0.8,
                    joints=list(violation.joints),
                    correction=violation.correction,
                    consecutive_frames=streak,
                ))
        elif result:
            for index, message in enumerate(result.violations):
                code = self._slug(message)
                active_codes.add(code)
                streak = self._violation_streaks.get(code, 0) + 1
                self._violation_streaks[code] = streak
                correction = result.corrections[index] if index < len(result.corrections) else ""
                items.append(ViolationItem(
                    type=code,
                    message=message,
                    correction=correction,
                    consecutive_frames=streak,
                ))

        for code in list(self._violation_streaks):
            if code not in active_codes:
                del self._violation_streaks[code]
        return items

    def _recognition_event(
        self,
        current: Optional[str],
        confidence: float,
        timestamp_ms: float,
    ) -> Optional[RecognitionEvent]:
        if not current or current == self._last_exercise:
            return None
        event_name = "exercise_confirmed" if self._last_exercise is None else "exercise_switched"
        self._last_exercise = current
        display = _DISPLAY_ZH.get(current, current)
        return RecognitionEvent(
            event=event_name,
            session_id=self.session_id,
            timestamp_ms=timestamp_ms,
            exercise=current,
            confidence=max(0.0, min(1.0, float(confidence))),
            specialist=f"{current}_specialist",
            message=f"小主，识别到您正在做{display}，我这就去找{display}专家带您锻炼哦。",
        )

    def _is_quality_declining(self) -> bool:
        if len(self._quality_history) < self._quality_history.maxlen:
            return False
        values = list(self._quality_history)
        early = sum(values[:4]) / 4.0
        recent = sum(values[-4:]) / 4.0
        return early - recent >= 0.15

    @staticmethod
    def _pose_quality(signal_quality: str) -> str:
        if signal_quality == "good":
            return "good"
        if signal_quality in {"acceptable", "degraded"}:
            return "acceptable"
        return "unreliable"

    @staticmethod
    def _slug(message: str) -> str:
        return "_".join(
            part for part in "".join(
                char.lower() if char.isalnum() else " " for char in message
            ).split() if part
        ) or "form_issue"

"""
Hold timing for static (yoga) poses.

Where the dynamic exercises count flex-extend *cycles* with a Schmitt trigger
(see ``pipeline/rep_counter.py``), yoga poses are scored by how long the body
stays correctly in a single static pose. ``HoldTimer`` is the time-based
analogue: feed it one boolean per frame ("is the body in the target pose right
now?") and it reports how long the current hold has lasted, how close it is to
the target, and whether the target was just reached.

A short **debounce** window absorbs MediaPipe jitter: a brief drop of a frame or
two (the pose detector momentarily losing a joint) does not reset a hold in
progress. Only a sustained loss past ``debounce_frames`` resets the timer.

Timing is wall-clock based (``time.time()``) so it is independent of frame rate.
"""

import time


class HoldTimer:
    """Tracks continuous time-in-pose with jitter debouncing.

    Call :meth:`update` once per frame. While ``is_in_pose`` is True the hold
    duration grows monotonically. A run of ``is_in_pose=False`` frames up to and
    including ``debounce_frames`` is tolerated (the hold keeps running); the
    first miss frame *beyond* that window resets the hold to zero.
    """

    def __init__(self, target_seconds: float, debounce_frames: int = 10):
        self.target_seconds = float(target_seconds)
        self.debounce_frames = int(debounce_frames)
        self.reset()

    def reset(self) -> None:
        self._hold_start: float | None = None  # wall-clock start of the current hold
        self._miss_streak: int = 0             # consecutive not-in-pose frames
        self._completed: bool = False          # latched once target reached this hold
        self._last_duration: float = 0.0

    def update(self, is_in_pose: bool) -> dict:
        """Advance the timer by one frame.

        Returns a dict: ``{duration, progress (0..1), complete, just_completed}``.
        ``just_completed`` is True only on the single frame the target is first
        reached for the current hold.
        """
        now = time.time()

        if is_in_pose:
            self._miss_streak = 0
            if self._hold_start is None:
                self._hold_start = now
        else:
            self._miss_streak += 1
            if self._miss_streak > self.debounce_frames:
                # Sustained loss of the pose — drop the hold entirely.
                self.reset()
                return self._zero()
            if self._hold_start is None:
                # Nothing was being held; stay at zero.
                return self._zero()
            # Within the debounce grace window: keep the existing hold running.

        duration = now - self._hold_start
        return self._evaluate(duration)

    def _evaluate(self, duration: float) -> dict:
        if self.target_seconds <= 0:
            progress = 1.0
            complete = True
        else:
            progress = min(1.0, duration / self.target_seconds)
            complete = duration >= self.target_seconds

        just_completed = complete and not self._completed
        if just_completed:
            self._completed = True

        self._last_duration = duration
        return {
            "duration": duration,
            "progress": progress,
            "complete": complete,
            "just_completed": just_completed,
        }

    def _zero(self) -> dict:
        self._last_duration = 0.0
        return {
            "duration": 0.0,
            "progress": 0.0,
            "complete": False,
            "just_completed": False,
        }

    @property
    def duration(self) -> float:
        return self._last_duration

    @property
    def is_complete(self) -> bool:
        return self._completed

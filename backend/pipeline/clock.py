"""Observation time scoped to a frame, isolated across threads and tasks."""
from contextlib import contextmanager
from contextvars import ContextVar
import time

_observation = ContextVar("fitness_observation_time", default=None)


def now():
    value = _observation.get()
    return time.time() if value is None else value


def monotonic():
    value = _observation.get()
    return time.monotonic() if value is None else value


@contextmanager
def observation_time(seconds):
    token = _observation.set(seconds)
    try:
        yield
    finally:
        _observation.reset(token)

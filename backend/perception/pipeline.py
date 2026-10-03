"""One measured pipeline shared by WebSocket ingestion and offline evaluation."""
import math
import time
from pipeline.clock import observation_time


def process_pose_frame(form_manager, builder, perception, payload):
    stamp = payload.get("timestamp", time.time()*1000)
    if type(stamp) not in {int,float} or not math.isfinite(stamp) or stamp <= 0:
        raise ValueError("timestamp must be positive and finite")
    with observation_time(stamp/1000):
        return _process_pose_frame(form_manager, builder, perception, payload, stamp)


def _process_pose_frame(form_manager, builder, perception, payload, stamp):
    started = time.perf_counter()
    previous = perception.last_input_timestamp_ms
    if previous is not None and (stamp <= previous or stamp-previous > 750):
        form_manager.reset()
        builder.reset()
        perception.reset(clear_buffer=False)
    perception.last_input_timestamp_ms = stamp
    state = form_manager.process_frame(payload.get("landmarks", []), payload.get("client_probs"), payload.get("image_aspect_ratio", 1))
    recognized_at = time.perf_counter()
    report, event = builder.build(state, float(stamp))
    requested = payload.get("camera_view")
    policy = perception.update(report, state.filtered_landmarks, payload.get("world_landmarks"),
                               payload.get("capture_profile"), state.camera_view, requested,
                               form_manager._kalman.observation_metadata)
    finished = time.perf_counter()
    timings = {"recognition_ms": (recognized_at-started)*1000,
               "kinematics_evidence_ms": (finished-recognized_at)*1000, "total_ms": (finished-started)*1000}
    return state, report, event, policy, timings

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from training.build_windows import make_windows, process_segment


class FakeCapture:
    def __init__(self, _path):
        self.index = 0

    def isOpened(self):
        return self.index < 60

    def get(self, _property):
        return 30.0

    def set(self, _property, _value):
        return True

    def read(self):
        if self.index >= 60:
            return False, None
        self.index += 1
        return True, np.zeros((2, 2, 3), dtype=np.uint8)

    def release(self):
        return None


class FakeDetector:
    def __init__(self):
        self.timestamps = []

    def detect_for_video(self, _image, timestamp):
        self.timestamps.append(timestamp)
        return SimpleNamespace(pose_landmarks=[])


class BuildWindowsSamplingTests(unittest.TestCase):
    def test_source_video_is_sampled_at_target_rate(self):
        detector = FakeDetector()
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch("training.build_windows.cv2.VideoCapture", FakeCapture),
                patch("training.build_windows.cv2.cvtColor", side_effect=lambda frame, _mode: frame),
                patch("training.build_windows.mp.Image", side_effect=lambda **kwargs: kwargs),
            ):
                process_segment(
                    detector,
                    {"path": "clip.mp4", "label": "plank", "subject": "p01"},
                    Path(directory),
                    target_fps=15.0,
                )

        self.assertEqual(len(detector.timestamps), 30)
        self.assertEqual(detector.timestamps[:3], [0, 67, 133])
        self.assertTrue(all(
            right > left
            for left, right in zip(detector.timestamps, detector.timestamps[1:])
        ))

    def test_short_curated_clip_can_be_resampled_without_changing_endpoints(self):
        frames = [
            np.full((17, 3), value, dtype=np.float32)
            for value in range(10)
        ]
        windows = make_windows(frames, 30, 10, 160, "resample", 8)

        self.assertEqual(windows.shape, (1, 30, 17, 3))
        np.testing.assert_array_equal(windows[0, 0], frames[0])
        np.testing.assert_array_equal(windows[0, -1], frames[-1])

    def test_too_short_clip_is_still_rejected(self):
        frames = [np.zeros((17, 3), dtype=np.float32) for _ in range(7)]
        windows = make_windows(frames, 30, 10, 160, "resample", 8)
        self.assertEqual(windows.shape[0], 0)


if __name__ == "__main__":
    unittest.main()

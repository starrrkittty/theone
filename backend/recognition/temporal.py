"""Motion evidence for recognition; these thresholds are engineering heuristics."""
from collections import deque
import numpy as np

POINTS = {"left_knee":(23,25,27), "right_knee":(24,26,28),
          "left_elbow":(11,13,15), "right_elbow":(12,14,16),
          "left_shoulder":(13,11,23), "right_shoulder":(14,12,24)}


class TemporalEvidence:
    def __init__(self, seconds=2.5, min_range=12.0):
        self.seconds = seconds
        self.min_range = min_range
        self.samples = deque(maxlen=180)

    def reset(self):
        self.samples.clear()

    def update(self, frame, now):
        angles = {name:frame.angles[name] for name, indices in POINTS.items()
                  if name in frame.angles and min(frame.visibility[list(indices)]) >= 0.5}
        self.samples.append((now, angles))
        while self.samples and now - self.samples[0][0] > self.seconds:
            self.samples.popleft()

    def motion_range(self, joint):
        values = [(stamp, angles[joint]) for stamp, angles in self.samples if joint in angles]
        if len(values) < 4 or values[-1][0] - values[0][0] < 0.15:
            return 0.0
        ordered = sorted(value for _, value in values)
        # Trim extreme samples to avoid confirming movement from one pose spike.
        trim = max(1, len(ordered) // 10)
        return ordered[-trim-1] - ordered[trim]

    def moving(self, joint):
        return self.motion_range(joint) >= self.min_range

    def alternating(self):
        pairs = [(angles["left_elbow"], angles["right_elbow"])
                 for _, angles in self.samples
                 if "left_elbow" in angles and "right_elbow" in angles]
        if len(pairs) < 4 or not all(self.moving(side+"_elbow") for side in ("left", "right")):
            return False
        return bool(np.corrcoef(np.asarray(pairs).T)[0, 1] < -0.25)

    def curl_supported(self):
        # Supported variants keep the upper arm near the torso. Competing
        # motion causes abstention, not an anatomical diagnosis.
        if any(self.moving(side+"_knee") for side in ("left", "right")):
            return False
        for side in ("left", "right"):
            elbow_range = self.motion_range(side+"_elbow")
            if elbow_range < self.min_range:
                continue
            shoulder_range = self.motion_range(side+"_shoulder")
            current = self.samples[-1][1] if self.samples else {}
            if current.get(side+"_shoulder", 0) > 65:
                continue
            if shoulder_range >= self.min_range and shoulder_range >= elbow_range:
                continue
            return True
        return False

    def supports(self, exercise):
        if exercise == "plank":
            return True
        if exercise in {"bicep_curl", "alternate_bicep_curl"}:
            return self.curl_supported() and (exercise != "alternate_bicep_curl" or self.alternating())
        if exercise == "squat" and self.samples:
            current = self.samples[-1][1]
            knees = [current[name] for name in ("left_knee", "right_knee") if name in current]
            if len(knees) == 2:
                # The supported squat is bilateral. A unilateral bend must not
                # be confirmed merely because its mean knee angle is low.
                return (abs(knees[0]-knees[1]) <= 30
                        and all(self.moving(side+"_knee") for side in ("left", "right")))
        joints = ("left_knee", "right_knee") if exercise == "squat" else ("left_elbow", "right_elbow")
        return any(self.moving(joint) for joint in joints)

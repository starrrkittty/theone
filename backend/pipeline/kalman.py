"""Per-landmark constant-velocity Kalman tracker for 33 MediaPipe landmarks."""

import numpy as np
from dataclasses import dataclass
from typing import Optional


@dataclass
class KalmanConfig:
    process_noise_pos: float = 1e-3
    process_noise_vel: float = 1e-2
    base_measurement_noise: float = 1e-2
    min_visibility: float = 0.05
    reference_fps: float = 30.0


class KalmanPoseTracker:
    """
    33 independent 6-state (x,y,z,vx,vy,vz) constant-velocity Kalman filters.
    Measurement noise is scaled by 1/visibility so low-confidence observations
    contribute less to the update.
    """

    def __init__(self, config: Optional[KalmanConfig] = None):
        self.config = config or KalmanConfig()
        self._initialized = False
        self._last_timestamp = None
        self._tracking_time = 0.0
        self._last_reliable_time = np.full(33, np.nan)
        self.observation_metadata = []
        # State: (33, 6) — [x, y, z, vx, vy, vz] per landmark
        self._x = np.zeros((33, 6), dtype=np.float64)
        # Covariance: (33, 6, 6)
        self._P = np.stack([np.eye(6) for _ in range(33)])
        self._build_matrices()

    def _build_matrices(self):
        cfg = self.config
        dt = 1.0  # one frame step
        # Transition matrix F (6x6)
        self._F = np.eye(6)
        self._F[0, 3] = dt
        self._F[1, 4] = dt
        self._F[2, 5] = dt

        # Measurement matrix H (3x6) — observe [x,y,z]
        self._H = np.zeros((3, 6))
        self._H[0, 0] = 1.0
        self._H[1, 1] = 1.0
        self._H[2, 2] = 1.0

        # Process noise Q (6x6)
        qp = cfg.process_noise_pos
        qv = cfg.process_noise_vel
        self._Q = np.diag([qp, qp, qp, qv, qv, qv])

        # Base measurement noise R (3x3) — scaled per-frame by visibility
        self._R_base = np.eye(3) * cfg.base_measurement_noise

        # Identity for covariance update
        self._I = np.eye(6)

    def update(self, landmarks: np.ndarray, timestamp_seconds: Optional[float] = None) -> tuple[np.ndarray, np.ndarray]:
        """
        Update all 33 filters with new landmark observations.

        Args:
            landmarks: shape (33, 4) — columns [x, y, z, visibility]

        Returns:
            smoothed_xyz: shape (33, 3) — filtered [x, y, z]
            uncertainty: shape (33,) — trace of position covariance per landmark
        """
        dt = 1.0
        if timestamp_seconds is not None:
            if not np.isfinite(timestamp_seconds):
                raise ValueError('Filter timestamp must be finite')
            if self._last_timestamp is not None:
                elapsed = timestamp_seconds-self._last_timestamp
                if elapsed <= 0 or elapsed > .75:
                    self.reset()
                else:
                    dt = max(.01, elapsed*self.config.reference_fps)
            self._last_timestamp = timestamp_seconds
        if not self._initialized:
            self._x[:, :3] = landmarks[:, :3]
            self._initialized = True

        F = self._F.copy()
        F[:3, 3:] = np.eye(3)*dt
        H = self._H
        Q = self._Q*dt
        I = self._I

        # Batch independent landmark filters; Joseph form preserves covariance
        # symmetry and positive semidefiniteness under floating-point rounding.
        visibility = np.maximum(landmarks[:, 3], self.config.min_visibility)
        tracking_now=timestamp_seconds if timestamp_seconds is not None else self._tracking_time+1/self.config.reference_fps
        self._tracking_time=tracking_now
        reliable=landmarks[:,3]>=.3
        self._last_reliable_time[reliable]=tracking_now
        x_pred = self._x @ F.T
        P_pred = F @ self._P @ F.T + Q
        R = self._R_base[None, :, :] / visibility[:, None, None]
        S = H @ P_pred @ H.T + R
        PH = P_pred @ H.T
        K = np.linalg.solve(S, PH.transpose(0, 2, 1)).transpose(0, 2, 1)
        # Hidden landmark coordinates are predictions, not new measurements.
        K[landmarks[:, 3] < self.config.min_visibility] = 0
        innovation = landmarks[:, :3].astype(np.float64) - x_pred @ H.T
        self._x = x_pred + (K @ innovation[..., None])[..., 0]
        residual = I - K @ H
        self._P = residual @ P_pred @ residual.transpose(0, 2, 1) + K @ R @ K.transpose(0, 2, 1)

        smoothed_xyz = self._x[:, :3].copy().astype(np.float32)
        # Uncertainty = trace of position block (top-left 3x3 of covariance)
        uncertainty = np.trace(self._P[:, :3, :3], axis1=1, axis2=2).astype(np.float32)
        self.observation_metadata = [{"index":i,
            "source":"filtered_observation" if reliable[i] else "prediction_only" if landmarks[i,3]<self.config.min_visibility else "low_confidence_model_estimate",
            "visibility":float(landmarks[i,3]),
            "age_since_reliable_ms":round((tracking_now-self._last_reliable_time[i])*1000,1) if np.isfinite(self._last_reliable_time[i]) else None,
            "filter_covariance_trace":float(uncertainty[i]),
            "usable_as_observed_evidence":bool(reliable[i])} for i in range(33)]

        return smoothed_xyz, uncertainty

    def reset(self):
        self._initialized = False
        self._last_timestamp = None
        self._tracking_time = 0.0
        self._last_reliable_time = np.full(33, np.nan)
        self.observation_metadata = []
        self._x = np.zeros((33, 6), dtype=np.float64)
        self._P = np.stack([np.eye(6) for _ in range(33)])

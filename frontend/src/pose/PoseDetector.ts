/**
 * MediaPipe Pose Landmarker wrapper for client-side pose estimation.
 * Uses the new @mediapipe/tasks-vision API which works better with Vite.
 */

import {
  PoseLandmarker,
  FilesetResolver,
  NormalizedLandmark,
} from '@mediapipe/tasks-vision';
import { MEDIAPIPE_MODEL_PATH, MEDIAPIPE_WASM_PATH } from '../config';

export interface PoseLandmark {
  x: number;
  y: number;
  z: number;
  visibility: number;
}

export interface PoseResult {
  landmarks: PoseLandmark[];
  worldLandmarks: PoseLandmark[];
  timestamp: number;
  tracking: PoseTrackingInfo;
}

export interface PoseTrackingInfo {
  personCount: number;
  selectedPoseIndex: number;
  subjectLocked: boolean;
  ambiguity: number;
  warning: string | null;
}

export type OnResultsCallback = (result: PoseResult) => void;

// MediaPipe pose landmark connections for drawing
export const POSE_CONNECTIONS: [number, number][] = [
  [0, 1], [1, 2], [2, 3], [3, 7], // face
  [0, 4], [4, 5], [5, 6], [6, 8], // face
  [9, 10], // mouth
  [11, 12], // shoulders
  [11, 13], [13, 15], // left arm
  [12, 14], [14, 16], // right arm
  [15, 17], [15, 19], [15, 21], [17, 19], // left hand
  [16, 18], [16, 20], [16, 22], [18, 20], // right hand
  [11, 23], [12, 24], [23, 24], // torso
  [23, 25], [25, 27], // left leg
  [24, 26], [26, 28], // right leg
  [27, 29], [29, 31], [27, 31], // left foot
  [28, 30], [30, 32], [28, 32], // right foot
];

export class PoseDetector {
  private poseLandmarker: PoseLandmarker | null = null;
  private isInitialized = false;
  private isInitializing = false;
  private onResultsCallback: OnResultsCallback | null = null;
  private processingFrame = false;
  private initPromise: Promise<void> | null = null;
  private lastSubjectCenter: { x: number; y: number } | null = null;

  constructor() {
    // Don't auto-initialize - let consumer call initialize()
  }

  async initialize(): Promise<void> {
    if (this.isInitialized) {
      return;
    }

    if (this.isInitializing && this.initPromise) {
      return this.initPromise;
    }

    this.isInitializing = true;
    this.initPromise = this.doInitialize();

    try {
      await this.initPromise;
    } finally {
      this.isInitializing = false;
    }
  }

  private async doInitialize(): Promise<void> {
    try {
      console.log('Initializing PoseLandmarker...');

      // Create the fileset resolver to load WASM files
      const vision = await FilesetResolver.forVisionTasks(
        MEDIAPIPE_WASM_PATH
      );

      // Create the pose landmarker
      this.poseLandmarker = await PoseLandmarker.createFromOptions(vision, {
        baseOptions: {
          modelAssetPath: MEDIAPIPE_MODEL_PATH,
          delegate: 'GPU',
        },
        runningMode: 'VIDEO',
        numPoses: 3,
        minPoseDetectionConfidence: 0.5,
        minPosePresenceConfidence: 0.5,
        minTrackingConfidence: 0.5,
        outputSegmentationMasks: false,
      });

      this.isInitialized = true;
      console.log('PoseLandmarker initialized successfully');
    } catch (error) {
      console.error('Failed to initialize PoseLandmarker:', error);
      this.isInitialized = false;
      throw error;
    }
  }

  /**
   * Set callback for pose detection results.
   */
  onResults(callback: OnResultsCallback): void {
    this.onResultsCallback = callback;
  }

  /**
   * Process a video frame for pose detection (for new tasks-vision API).
   */
  async processFrame(
    videoElement: HTMLVideoElement,
    timestamp?: number
  ): Promise<PoseResult | null> {
    if (!this.isInitialized || !this.poseLandmarker) {
      return null;
    }

    if (this.processingFrame) {
      return null;
    }

    if (videoElement.readyState < 2) {
      return null;
    }

    this.processingFrame = true;

    try {
      const startTime = timestamp ?? performance.now();
      const results = this.poseLandmarker.detectForVideo(videoElement, startTime);

      if (!results.landmarks || results.landmarks.length === 0) {
        return null;
      }

      const selection = this.selectPrimaryPose(results.landmarks);
      const selectedWorld = results.worldLandmarks?.[selection.index] ?? [];
      const poseResult: PoseResult = {
        landmarks: results.landmarks[selection.index].map((lm: NormalizedLandmark) => ({
          x: lm.x,
          y: lm.y,
          z: lm.z,
          visibility: lm.visibility ?? 0,
        })),
        worldLandmarks: selectedWorld.map((lm: NormalizedLandmark) => ({
          x: lm.x,
          y: lm.y,
          z: lm.z,
          visibility: lm.visibility ?? 0,
        })) ?? [],
        timestamp: startTime,
        tracking: {
          personCount: results.landmarks.length,
          selectedPoseIndex: selection.index,
          subjectLocked: selection.locked,
          ambiguity: selection.ambiguity,
          warning: selection.warning,
        },
      };

      this.onResultsCallback?.(poseResult);
      return poseResult;
    } catch (error) {
      console.error('Error detecting pose:', error);
      return null;
    } finally {
      this.processingFrame = false;
    }
  }

  private selectPrimaryPose(poses: NormalizedLandmark[][]): {
    index: number;
    locked: boolean;
    ambiguity: number;
    warning: string | null;
  } {
    const descriptors = poses.map((pose, index) => {
      const core = [11, 12, 23, 24]
        .map(i => pose[i])
        .filter((lm): lm is NormalizedLandmark => Boolean(lm));
      const center = core.reduce(
        (acc, lm) => ({ x: acc.x + lm.x / core.length, y: acc.y + lm.y / core.length }),
        { x: 0, y: 0 },
      );
      const visible = pose.filter(lm => (lm.visibility ?? 0) >= 0.3);
      const xs = visible.map(lm => lm.x);
      const ys = visible.map(lm => lm.y);
      const area = xs.length
        ? (Math.max(...xs) - Math.min(...xs)) * (Math.max(...ys) - Math.min(...ys))
        : 0;
      const visibility = core.reduce((sum, lm) => sum + (lm.visibility ?? 0), 0) /
        Math.max(core.length, 1);
      const centerDistance = Math.hypot(center.x - 0.5, center.y - 0.5);
      const continuityDistance = this.lastSubjectCenter
        ? Math.hypot(center.x - this.lastSubjectCenter.x, center.y - this.lastSubjectCenter.y)
        : centerDistance;
      const continuity = Math.max(0, 1 - continuityDistance / 0.35);
      const centered = Math.max(0, 1 - centerDistance / 0.7);
      const size = Math.min(1, Math.sqrt(Math.max(area, 0)) * 2.2);
      const score = (this.lastSubjectCenter ? 0.6 : 0.35) * continuity
        + 0.25 * size
        + 0.2 * visibility
        + (this.lastSubjectCenter ? 0 : 0.2) * centered;
      return { index, center, continuityDistance, score };
    }).sort((a, b) => b.score - a.score);

    const best = descriptors[0];
    const second = descriptors[1];
    const ambiguity = second ? Math.max(0, 1 - Math.abs(best.score - second.score) / 0.2) : 0;
    const locked = poses.length === 1 || (
      best.continuityDistance <= 0.22 && (!second || ambiguity < 0.8)
    );
    if (locked || this.lastSubjectCenter === null) {
      this.lastSubjectCenter = best.center;
    }

    return {
      index: best.index,
      locked,
      ambiguity,
      warning: poses.length > 1
        ? locked
          ? `检测到${poses.length}人，已锁定主要锻炼者`
          : `检测到${poses.length}人，无法稳定锁定主要锻炼者`
        : null,
    };
  }

  /**
   * Check if detector is ready.
   */
  get ready(): boolean {
    return this.isInitialized && this.poseLandmarker !== null;
  }

  /**
   * Close and cleanup resources.
   */
  async close(): Promise<void> {
    if (this.poseLandmarker) {
      this.poseLandmarker.close();
      this.poseLandmarker = null;
    }
    this.isInitialized = false;
    this.onResultsCallback = null;
    this.lastSubjectCenter = null;
  }
}

/**
 * Get pose connections for drawing skeleton.
 */
export function getPoseConnections(): [number, number][] {
  return POSE_CONNECTIONS;
}

/**
 * Landmark indices for quick access.
 */
export const LANDMARK_INDICES = {
  NOSE: 0,
  LEFT_EYE_INNER: 1,
  LEFT_EYE: 2,
  LEFT_EYE_OUTER: 3,
  RIGHT_EYE_INNER: 4,
  RIGHT_EYE: 5,
  RIGHT_EYE_OUTER: 6,
  LEFT_EAR: 7,
  RIGHT_EAR: 8,
  MOUTH_LEFT: 9,
  MOUTH_RIGHT: 10,
  LEFT_SHOULDER: 11,
  RIGHT_SHOULDER: 12,
  LEFT_ELBOW: 13,
  RIGHT_ELBOW: 14,
  LEFT_WRIST: 15,
  RIGHT_WRIST: 16,
  LEFT_PINKY: 17,
  RIGHT_PINKY: 18,
  LEFT_INDEX: 19,
  RIGHT_INDEX: 20,
  LEFT_THUMB: 21,
  RIGHT_THUMB: 22,
  LEFT_HIP: 23,
  RIGHT_HIP: 24,
  LEFT_KNEE: 25,
  RIGHT_KNEE: 26,
  LEFT_ANKLE: 27,
  RIGHT_ANKLE: 28,
  LEFT_HEEL: 29,
  RIGHT_HEEL: 30,
  LEFT_FOOT_INDEX: 31,
  RIGHT_FOOT_INDEX: 32,
} as const;

/**
 * Map landmark index to joint name for color lookup.
 */
export function getLandmarkName(index: number): string {
  const names = Object.entries(LANDMARK_INDICES);
  const entry = names.find(([, idx]) => idx === index);
  return entry ? entry[0].toLowerCase() : `landmark_${index}`;
}

/**
 * MediaPipe Pose Landmarker wrapper for client-side pose estimation.
 * Uses the new @mediapipe/tasks-vision API which works better with Vite.
 */

import {
  PoseLandmarker,
  FilesetResolver,
  NormalizedLandmark,
} from '@mediapipe/tasks-vision';

export interface PoseLandmark {
  x: number;
  y: number;
  z: number;
  visibility: number;
}

export interface PoseResult {
  inferenceMs?: number;
  landmarks: PoseLandmark[];
  worldLandmarks: PoseLandmark[];
  timestamp: number;
}

export type OnResultsCallback = (result: PoseResult) => void;
export type PoseModel = 'lite' | 'full' | 'heavy';
export interface DetectorOptions {
  model?: PoseModel;
  modelAssetPath?: string;
  delegate?: 'GPU' | 'CPU';
}

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
  private closed = false;
  private lastTimestamp = -1;
  actualDelegate: 'GPU' | 'CPU' = 'GPU';

  constructor(private options: DetectorOptions = {}) {
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
        'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.8/wasm'
      );

      // Create the pose landmarker
      const model = this.options.model ?? 'lite';
      const delegate = this.options.delegate ?? 'GPU';
      const create = (selected: 'GPU' | 'CPU') => PoseLandmarker.createFromOptions(vision, {
        baseOptions: {
          modelAssetPath: this.options.modelAssetPath ?? `https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_${model}/float16/1/pose_landmarker_${model}.task`,
          delegate: selected,
        },
        runningMode: 'VIDEO',
        numPoses: 1,
        minPoseDetectionConfidence: 0.5,
        minPosePresenceConfidence: 0.5,
        minTrackingConfidence: 0.5,
        outputSegmentationMasks: false,
      });
      try {
        this.poseLandmarker = await create(delegate);
        this.actualDelegate = delegate;
      } catch (error) {
        if (delegate === 'CPU') throw error;
        this.poseLandmarker = await create('CPU');
        this.actualDelegate = 'CPU';
      }
      if (this.closed) {
        this.poseLandmarker.close();
        this.poseLandmarker = null;
        return;
      }

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
      if (!Number.isFinite(startTime) || startTime <= this.lastTimestamp) {
        throw new Error('Pose inference timestamps must increase');
      }
      this.lastTimestamp = startTime;
      const inferenceStarted = performance.now();
      const results = this.poseLandmarker.detectForVideo(videoElement, startTime);
      const inferenceMs = performance.now()-inferenceStarted;

      if (!results.landmarks || results.landmarks.length === 0) {
        const empty = { landmarks:[], worldLandmarks:[], timestamp:startTime, inferenceMs };
        this.onResultsCallback?.(empty);
        return empty;
      }

      const poseResult: PoseResult = {
        inferenceMs,
        landmarks: results.landmarks[0].map((lm: NormalizedLandmark) => ({
          x: lm.x,
          y: lm.y,
          z: lm.z,
          visibility: lm.visibility ?? 0,
        })),
        worldLandmarks: results.worldLandmarks?.[0]?.map((lm: NormalizedLandmark) => ({
          x: lm.x,
          y: lm.y,
          z: lm.z,
          visibility: lm.visibility ?? 0,
        })) ?? [],
        timestamp: startTime,
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
    this.closed = true;
    if (this.poseLandmarker) {
      this.poseLandmarker.close();
      this.poseLandmarker = null;
    }
    this.isInitialized = false;
    this.onResultsCallback = null;
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

/**
 * React hook for WebSocket connection to pose analysis backend.
 * Streams landmarks and receives form correction feedback.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { PoseLandmark } from '../pose';
import { WS_URL } from '../config';

export interface CandidateExercise {
  exercise: string;
  confidence: number;
  source: string;
}

export interface ActionViolation {
  type: string;
  message: string;
  severity: 'low' | 'medium' | 'high';
  confidence: number;
  joints: string[];
  correction: string;
  consecutive_frames: number;
}

export interface ActionReport {
  schema_version: 'v1';
  session_id: string;
  timestamp_ms: number;
  recognition_status: 'unknown' | 'candidate' | 'confirmed';
  recognized_exercise: string;
  recognition_confidence: number;
  candidate_exercises: CandidateExercise[];
  specialist: string | null;
  phase: string;
  repetition: number;
  pose_quality: 'good' | 'acceptable' | 'unreliable';
  camera_view: string;
  kinematics?: {
    status: string;
    model_id?: string;
    parser?: string;
    coordinate_units?: string;
    joint_states?: Record<string, {position_rad: number; velocity_rad_s: number | null; visibility: number}>;
    fk_endpoint_residuals_normalized?: Record<string, number>;
    [key: string]: unknown;
  };
  perception_agent?: {
    mode: string;
    decision: string;
    handoff_allowed: boolean;
    observation_request: string;
    reason: string;
    [key: string]: unknown;
  };
  metrics: {
    joint_angles: Record<string, number>;
    joint_confidences?: Record<string, number>;
    confidence_method?: string;
    hold_seconds: number;
    rep_quality: number | null;
    partial_reps: number;
  };
  violations: ActionViolation[];
  agent_context: {
    should_coach_now: boolean;
    priority: 'none' | 'encouragement' | 'form_correction' | 'safety';
    recommended_intent: string;
    repeated_error_count: number;
    possible_fatigue: boolean;
  };
}

export interface RecognitionEvent {
  event: 'exercise_confirmed' | 'exercise_switched';
  session_id: string;
  timestamp_ms: number;
  exercise: string;
  confidence: number;
  specialist: string;
  message: string;
}

export interface FormCorrectionResponse {
  state: 'idle' | 'stationary' | 'scanning' | 'active';
  current_exercise: string | null;
  exercise_display: string;
  rep_count: number;
  rep_phase: string;
  phase_display?: string;
  is_rep_valid: boolean;
  violations: string[];
  corrections: string[];
  correction_message: string;
  joint_colors: Record<string, string>;
  confidence: number;
  is_stationary?: boolean;
  timestamp: number;
  exercise_confidence?: number;
  form_confidence?: number;
  signal_quality?: string;
  exercise_variant?: string | null;
  exercise_source?: string;
  camera_view?: string;
  hold_seconds?: number;
  recognition_event?: RecognitionEvent | null;
  action_report?: ActionReport;
  capture?: { frames: number; capacity: number; dropped_frames: number; rejected_frames: number };
  processing?: {recognition_ms:number; kinematics_evidence_ms:number; total_ms:number; wire_bytes?:number; full_wire_bytes?:number};
}

export interface UsePoseStreamOptions {
  url?: string;
  clientId?: string;
  autoConnect?: boolean;
  onResponse?: (response: FormCorrectionResponse) => void;
  onError?: (error: Error) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
}

export interface UsePoseStreamReturn {
  isConnected: boolean;
  isConnecting: boolean;
  latestResponse: FormCorrectionResponse | null;
  error: Error | null;
  connect: () => void;
  disconnect: () => void;
  sendLandmarks: (landmarks: PoseLandmark[], timestamp: number, clientProbs?: Record<string, number> | null, imageAspectRatio?: number, worldLandmarks?: PoseLandmark[]) => void;
  reset: () => Promise<void>;
}

const DEFAULT_WS_URL = WS_URL;

export function buildPoseMessage(
  landmarks: PoseLandmark[],
  timestamp: number,
  clientProbs: Record<string, number> | null,
  imageAspectRatio?: number,
  worldLandmarks?: PoseLandmark[],
): string {
  const payload: {
    landmarks: { x: number; y: number; z: number; visibility: number }[];
    timestamp: number;
    client_probs?: Record<string, number>;
    image_aspect_ratio?: number;
    world_landmarks?: PoseLandmark[];
    capture_profile: string;
    camera_view: string;
    response_mode: string;
  } = {
    landmarks: landmarks.map(lm => ({ x: lm.x, y: lm.y, z: lm.z, visibility: lm.visibility })),
    timestamp,
    capture_profile: 'exercise_view_v1',
    camera_view: 'auto',
    response_mode: 'compact',
  };
  if (clientProbs !== null && clientProbs !== undefined) {
    payload.client_probs = clientProbs;
  }
  if (imageAspectRatio !== undefined) payload.image_aspect_ratio = imageAspectRatio;
  if (worldLandmarks?.length === 33) payload.world_landmarks = worldLandmarks;
  return JSON.stringify(payload);
}

// Generate stable client ID once
const stableClientId = `client_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

export function usePoseStream(options: UsePoseStreamOptions = {}): UsePoseStreamReturn {
  const {
    url = DEFAULT_WS_URL,
    clientId: providedClientId,
    autoConnect = false,
    onResponse,
    onError,
    onConnect,
    onDisconnect,
  } = options;

  const [isConnected, setIsConnected] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [latestResponse, setLatestResponse] = useState<FormCorrectionResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);

  // Use refs to store stable values
  const wsRef = useRef<WebSocket | null>(null);
  const clientIdRef = useRef(providedClientId || stableClientId);
  const pendingMessagesRef = useRef<string[]>([]);
  const mountedRef = useRef(true);
  const connectingRef = useRef(false);
  const lastSentAt = useRef(0);
  const lastReceivedAt = useRef(0);

  // Store callbacks in refs to avoid dependency issues
  const callbacksRef = useRef({ onResponse, onError, onConnect, onDisconnect });

  // Update callbacks ref when they change
  useEffect(() => {
    callbacksRef.current = { onResponse, onError, onConnect, onDisconnect };
  }, [onResponse, onError, onConnect, onDisconnect]);

  const disconnect = useCallback(() => {
    connectingRef.current = false;

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    setIsConnected(false);
    setIsConnecting(false);
  }, []);

  const connect = useCallback(() => {
    // Prevent multiple simultaneous connections - comprehensive check
    if (connectingRef.current) {
      console.log('Already connecting, skipping...');
      return;
    }

    if (wsRef.current) {
      const state = wsRef.current.readyState;
      if (state === WebSocket.CONNECTING || state === WebSocket.OPEN) {
        console.log('WebSocket already open or connecting, skipping...');
        return;
      }
    }

    connectingRef.current = true;
    setIsConnecting(true);
    setError(null);

    const wsUrl = `${url}/${clientIdRef.current}`;
    console.log('Connecting to WebSocket:', wsUrl);

    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      if (!mountedRef.current || wsRef.current !== ws) {
        ws.close();
        return;
      }

      console.log('WebSocket connected');
      connectingRef.current = false;
      setIsConnected(true);
      lastReceivedAt.current = 0;
      setIsConnecting(false);
      callbacksRef.current.onConnect?.();

      // Send any pending messages
      const newest = pendingMessagesRef.current.pop();
      pendingMessagesRef.current = [];
      if (newest) ws.send(newest);
    };

    ws.onmessage = (event) => {
      if (!mountedRef.current || wsRef.current !== ws) return;

      try {
        const response: FormCorrectionResponse = JSON.parse(event.data);
        if ('error' in response) {
          callbacksRef.current.onError?.(new Error(String((response as unknown as {error:unknown}).error)));
          return;
        }
        if (Date.now()-response.timestamp > 2000 || response.timestamp <= lastReceivedAt.current) return;
        lastReceivedAt.current = response.timestamp;
        setLatestResponse(response);
        callbacksRef.current.onResponse?.(response);
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };

    ws.onerror = (_event) => {
      if (!mountedRef.current || wsRef.current !== ws) return;

      const err = new Error('WebSocket error');
      setError(err);
      callbacksRef.current.onError?.(err);
    };

    ws.onclose = () => {
      if (!mountedRef.current || wsRef.current !== ws) return;

      console.log('WebSocket disconnected');
      connectingRef.current = false;
      setIsConnected(false);
      setIsConnecting(false);
      callbacksRef.current.onDisconnect?.();
      wsRef.current = null;
    };

    wsRef.current = ws;
  }, [url]);

  const sendLandmarks = useCallback(
    (landmarks: PoseLandmark[], timestamp: number, clientProbs?: Record<string, number> | null, imageAspectRatio?: number, worldLandmarks?: PoseLandmark[]) => {
      const now = performance.now();
      if (lastSentAt.current && now-lastSentAt.current < 50) return;
      lastSentAt.current = now;
      const message = buildPoseMessage(landmarks, timestamp, clientProbs ?? null, imageAspectRatio, worldLandmarks);

      if (wsRef.current?.readyState === WebSocket.OPEN) {
        if (wsRef.current.bufferedAmount > 64000) return;
        wsRef.current.send(message);
      } else {
        pendingMessagesRef.current = [message];
      }
    },
    [],
  );

  const reset = useCallback(async () => {
    try {
      const response = await fetch(`/api/reset/${clientIdRef.current}`, {
        method: 'POST',
      });

      if (!response.ok) {
        throw new Error('Failed to reset session');
      }

      setLatestResponse(null);
      lastReceivedAt.current = 0;
    } catch (e) {
      const err = e instanceof Error ? e : new Error('Failed to reset');
      setError(err);
      callbacksRef.current.onError?.(err);
    }
  }, []);

  // Mount/unmount tracking
  useEffect(() => {
    mountedRef.current = true;

    return () => {
      mountedRef.current = false;
      // Clean up connection on unmount
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      connectingRef.current = false;
    };
  }, []);  // Empty deps - only run on mount/unmount

  // Auto-connect on mount if enabled (only once, disabled by default)
  useEffect(() => {
    if (!autoConnect) return;

    // Don't reconnect if already connected or connecting
    if (wsRef.current || connectingRef.current) return;

    // Small delay to prevent React strict mode double-connect
    const timer = setTimeout(() => {
      if (mountedRef.current && !wsRef.current && !connectingRef.current) {
        connect();
      }
    }, 200);

    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);  // Empty deps - only auto-connect on initial mount

  return {
    isConnected,
    isConnecting,
    latestResponse,
    error,
    connect,
    disconnect,
    sendLandmarks,
    reset,
  };
}

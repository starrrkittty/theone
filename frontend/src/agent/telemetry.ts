import type { FormCorrectionResponse } from '../hooks/usePoseStream';

export const EVALUATION_EXERCISES = [
  'squat',
  'pushup',
  'plank',
  'bicep_curl',
  'alternate_bicep_curl',
  'dumbbell_row',
  'jumping_jack',
  'lateral_raise',
  'lunge',
  'shoulder_press',
  'situp',
  'tricep_extension',
  'burpee',
  'jump_rope',
  'pullup',
  'running_in_place',
  'yoga_tree',
  'yoga_triangle',
  'unknown',
] as const;

export type EvaluationExercise = (typeof EVALUATION_EXERCISES)[number];

export interface AgentTelemetryFrame {
  elapsedMs: number;
  expectedExercise: EvaluationExercise | null;
  recognitionStatus: 'unknown' | 'candidate' | 'confirmed';
  recognizedExercise: string;
  recognitionConfidence: number;
  formConfidence: number;
  poseQuality: string | null;
  cameraView: string | null;
  rejectionReason: string | null;
  recognitionEvent: 'exercise_confirmed' | 'exercise_switched' | null;
  clientModelId: string | null;
}

export interface AgentTelemetry {
  startedAtMs: number | null;
  frames: number;
  confirmedFrames: number;
  candidateFrames: number;
  unknownFrames: number;
  unreliableFrames: number;
  recognitionEvents: number;
  exerciseSwitches: number;
  recognitionConfidenceSum: number;
  formConfidenceSum: number;
  firstConfirmedLatencyMs: number | null;
  evaluatedConfirmedFrames: number;
  correctConfirmedFrames: number;
  incorrectConfirmedFrames: number;
  trace: AgentTelemetryFrame[];
}

export interface AgentTelemetrySummary {
  averageRecognitionConfidence: number;
  averageFormConfidence: number;
  unknownRate: number;
  unreliableRate: number;
  confirmedAccuracy: number | null;
  firstConfirmedLatencyMs: number | null;
}

export function createAgentTelemetry(): AgentTelemetry {
  return {
    startedAtMs: null,
    frames: 0,
    confirmedFrames: 0,
    candidateFrames: 0,
    unknownFrames: 0,
    unreliableFrames: 0,
    recognitionEvents: 0,
    exerciseSwitches: 0,
    recognitionConfidenceSum: 0,
    formConfidenceSum: 0,
    firstConfirmedLatencyMs: null,
    evaluatedConfirmedFrames: 0,
    correctConfirmedFrames: 0,
    incorrectConfirmedFrames: 0,
    trace: [],
  };
}

export function accumulateAgentTelemetry(
  previous: AgentTelemetry,
  response: FormCorrectionResponse,
  observedAtMs: number,
  expectedExercise: EvaluationExercise | null,
): AgentTelemetry {
  const report = response.action_report;
  const status = report?.recognition_status ?? (
    response.current_exercise ? 'confirmed' : 'unknown'
  );
  const recognizedExercise = report?.recognized_exercise ?? response.current_exercise ?? 'unknown';
  const recognitionConfidence = report?.recognition_confidence
    ?? response.exercise_confidence
    ?? 0;
  const formConfidence = response.form_confidence ?? response.confidence ?? 0;
  const startedAtMs = previous.startedAtMs ?? observedAtMs;
  const newlyConfirmed = status === 'confirmed';
  const shouldEvaluate = newlyConfirmed && expectedExercise !== null;
  const isCorrect = shouldEvaluate && recognizedExercise === expectedExercise;
  const traceFrame: AgentTelemetryFrame = {
    elapsedMs: Math.max(0, observedAtMs - startedAtMs),
    expectedExercise,
    recognitionStatus: status,
    recognizedExercise,
    recognitionConfidence,
    formConfidence,
    poseQuality: report?.pose_quality ?? response.signal_quality ?? null,
    cameraView: report?.camera_view ?? response.camera_view ?? null,
    rejectionReason: response.recognition_debug?.rejection_reason ?? null,
    recognitionEvent: response.recognition_event?.event ?? null,
    clientModelId: response.recognition_debug?.semantic?.client_model_id ?? null,
  };

  return {
    startedAtMs,
    frames: previous.frames + 1,
    confirmedFrames: previous.confirmedFrames + (newlyConfirmed ? 1 : 0),
    candidateFrames: previous.candidateFrames + (status === 'candidate' ? 1 : 0),
    unknownFrames: previous.unknownFrames + (status === 'unknown' ? 1 : 0),
    unreliableFrames: previous.unreliableFrames + (
      report?.pose_quality === 'unreliable' || response.signal_quality === 'unreliable' ? 1 : 0
    ),
    recognitionEvents: previous.recognitionEvents + (response.recognition_event ? 1 : 0),
    exerciseSwitches: previous.exerciseSwitches + (
      response.recognition_event?.event === 'exercise_switched' ? 1 : 0
    ),
    recognitionConfidenceSum: previous.recognitionConfidenceSum + recognitionConfidence,
    formConfidenceSum: previous.formConfidenceSum + formConfidence,
    firstConfirmedLatencyMs: previous.firstConfirmedLatencyMs ?? (
      newlyConfirmed ? Math.max(0, observedAtMs - startedAtMs) : null
    ),
    evaluatedConfirmedFrames: previous.evaluatedConfirmedFrames + (shouldEvaluate ? 1 : 0),
    correctConfirmedFrames: previous.correctConfirmedFrames + (isCorrect ? 1 : 0),
    incorrectConfirmedFrames: previous.incorrectConfirmedFrames + (
      shouldEvaluate && !isCorrect ? 1 : 0
    ),
    trace: [...previous.trace.slice(-4999), traceFrame],
  };
}

export function summarizeAgentTelemetry(
  telemetry: AgentTelemetry,
): AgentTelemetrySummary {
  const frameDivisor = Math.max(1, telemetry.frames);
  return {
    averageRecognitionConfidence: telemetry.recognitionConfidenceSum / frameDivisor,
    averageFormConfidence: telemetry.formConfidenceSum / frameDivisor,
    unknownRate: telemetry.unknownFrames / frameDivisor,
    unreliableRate: telemetry.unreliableFrames / frameDivisor,
    confirmedAccuracy: telemetry.evaluatedConfirmedFrames > 0
      ? telemetry.correctConfirmedFrames / telemetry.evaluatedConfirmedFrames
      : null,
    firstConfirmedLatencyMs: telemetry.firstConfirmedLatencyMs,
  };
}

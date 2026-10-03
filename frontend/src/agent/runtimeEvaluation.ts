import type { RecognitionEvent, ActionReport } from '../hooks/usePoseStream';
import type {
  AgentTelemetry,
  AgentTelemetrySummary,
  EvaluationExercise,
} from './telemetry';

export const RUNTIME_EVALUATION_SCHEMA = 'agent-a-runtime-evaluation/v1' as const;

export interface RuntimeEvaluationMetadata {
  participantId: string;
  clipId: string;
  sourceType: 'uploaded_video' | 'live_video_call';
  expectedExercise: EvaluationExercise;
  cameraView: 'front' | 'side' | 'oblique' | 'mixed';
  lighting: 'normal' | 'dim' | 'backlit' | 'mixed';
  occlusion: 'none' | 'partial' | 'severe';
  multiPerson: boolean;
  notes: string;
}

export interface RuntimeEvaluationExport {
  schema_version: typeof RUNTIME_EVALUATION_SCHEMA;
  exported_at: string;
  clip: {
    participant_id: string;
    clip_id: string;
    source_type: RuntimeEvaluationMetadata['sourceType'];
    expected_exercise: EvaluationExercise;
    camera_view: RuntimeEvaluationMetadata['cameraView'];
    lighting: RuntimeEvaluationMetadata['lighting'];
    occlusion: RuntimeEvaluationMetadata['occlusion'];
    multi_person: boolean;
    notes: string;
  };
  model: {
    client_model_id: string | null;
    action_report_schema: string | null;
  };
  duration_ms: number;
  telemetry: AgentTelemetry;
  summary: AgentTelemetrySummary;
  recognition_history: RecognitionEvent[];
  latest_action_report: ActionReport | null;
}

export function validateRuntimeEvaluationMetadata(
  metadata: Partial<RuntimeEvaluationMetadata>,
): string[] {
  const errors: string[] = [];
  if (!metadata.participantId?.trim()) errors.push('participantId is required');
  if (!metadata.clipId?.trim()) errors.push('clipId is required');
  if (!metadata.expectedExercise) errors.push('expectedExercise is required');
  return errors;
}

export function buildRuntimeEvaluationExport(
  metadata: RuntimeEvaluationMetadata,
  telemetry: AgentTelemetry,
  summary: AgentTelemetrySummary,
  recognitionHistory: RecognitionEvent[],
  latestActionReport: ActionReport | null,
  exportedAt = new Date(),
): RuntimeEvaluationExport {
  const validationErrors = validateRuntimeEvaluationMetadata(metadata);
  if (validationErrors.length > 0) {
    throw new Error(validationErrors.join('; '));
  }
  const latestTraceWithModel = [...telemetry.trace]
    .reverse()
    .find((frame) => frame.clientModelId);
  const durationMs = telemetry.trace.length > 0
    ? telemetry.trace[telemetry.trace.length - 1].elapsedMs
    : 0;

  return {
    schema_version: RUNTIME_EVALUATION_SCHEMA,
    exported_at: exportedAt.toISOString(),
    clip: {
      participant_id: metadata.participantId.trim(),
      clip_id: metadata.clipId.trim(),
      source_type: metadata.sourceType,
      expected_exercise: metadata.expectedExercise,
      camera_view: metadata.cameraView,
      lighting: metadata.lighting,
      occlusion: metadata.occlusion,
      multi_person: metadata.multiPerson,
      notes: metadata.notes.trim(),
    },
    model: {
      client_model_id: latestTraceWithModel?.clientModelId ?? null,
      action_report_schema: latestActionReport?.schema_version ?? null,
    },
    duration_ms: durationMs,
    telemetry,
    summary,
    recognition_history: recognitionHistory,
    latest_action_report: latestActionReport,
  };
}

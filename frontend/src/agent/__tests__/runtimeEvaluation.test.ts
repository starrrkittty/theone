import { describe, expect, it } from 'vitest';

import { createAgentTelemetry, summarizeAgentTelemetry } from '../telemetry';
import {
  buildRuntimeEvaluationExport,
  RUNTIME_EVALUATION_SCHEMA,
  validateRuntimeEvaluationMetadata,
} from '../runtimeEvaluation';

describe('runtime evaluation export', () => {
  it('requires participant, clip and ground truth identifiers', () => {
    expect(validateRuntimeEvaluationMetadata({})).toEqual([
      'participantId is required',
      'clipId is required',
      'expectedExercise is required',
    ]);
  });

  it('builds a stable versioned evidence bundle', () => {
    const telemetry = createAgentTelemetry();
    telemetry.trace.push({
      elapsedMs: 1250,
      expectedExercise: 'unknown',
      recognitionStatus: 'unknown',
      recognizedExercise: 'unknown',
      recognitionConfidence: 0.2,
      formConfidence: 0.4,
      poseQuality: 'good',
      cameraView: 'front',
      rejectionReason: 'no_supported_motion_match',
      recognitionEvent: null,
      clientModelId: 'model-v1',
    });

    const payload = buildRuntimeEvaluationExport(
      {
        participantId: ' p01 ',
        clipId: ' unknown-wave-01 ',
        sourceType: 'live_video_call',
        expectedExercise: 'unknown',
        cameraView: 'front',
        lighting: 'normal',
        occlusion: 'none',
        multiPerson: false,
        notes: '  wave  ',
      },
      telemetry,
      summarizeAgentTelemetry(telemetry),
      [],
      null,
      new Date('2026-10-04T00:00:00.000Z'),
    );

    expect(payload.schema_version).toBe(RUNTIME_EVALUATION_SCHEMA);
    expect(payload.clip).toMatchObject({
      participant_id: 'p01',
      clip_id: 'unknown-wave-01',
      expected_exercise: 'unknown',
      notes: 'wave',
    });
    expect(payload.duration_ms).toBe(1250);
    expect(payload.model.client_model_id).toBe('model-v1');
  });
});

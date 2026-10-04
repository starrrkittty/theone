import { describe, expect, it } from 'vitest';

import type { FormCorrectionResponse } from '../../hooks/usePoseStream';
import {
  accumulateAgentTelemetry,
  createAgentTelemetry,
  summarizeAgentTelemetry,
} from '../telemetry';

function response(
  status: 'unknown' | 'candidate' | 'confirmed',
  exercise = 'unknown',
): FormCorrectionResponse {
  return {
    state: status === 'confirmed' ? 'active' : 'scanning',
    current_exercise: status === 'confirmed' ? exercise : null,
    exercise_display: exercise,
    rep_count: 0,
    rep_phase: 'idle',
    is_rep_valid: true,
    violations: [],
    corrections: [],
    correction_message: '',
    joint_colors: {},
    confidence: 0.8,
    exercise_confidence: 0.9,
    form_confidence: 0.8,
    timestamp: 0,
    action_report: {
      schema_version: 'v2',
      session_id: 'test',
      report_id: 'test:1:1',
      session_generation: 1,
      sequence: 1,
      timestamp_ms: 0,
      recognition_status: status,
      recognized_exercise: exercise,
      recognition_confidence: 0.9,
      candidate_exercises: [],
      specialist: status === 'confirmed' ? `${exercise}_specialist` : null,
      phase: 'idle',
      repetition: 0,
      pose_quality: 'good',
      camera_view: 'front',
      metrics: {
        joint_angles: {},
        joint_confidences: {},
        confidence_method: 'missing',
        hold_seconds: 0,
        rep_quality: null,
        partial_reps: 0,
      },
      violations: [],
      agent_context: {
        should_coach_now: false,
        priority: 'none',
        recommended_intent: 'observe',
        repeated_error_count: 0,
        possible_fatigue: false,
      },
      recognition: {
        exercise_id: exercise,
        display_name: exercise,
        category: 'other',
        source: 'test',
        uncertainty_reason: null,
      },
      routing: {
        mode: status === 'confirmed' ? 'verified_specialist' : 'observe_more',
        specialist: status === 'confirmed' ? `${exercise}_specialist` : null,
        fallback_specialist: null,
      },
      capabilities: {
        semantic_recognition: status === 'confirmed',
        precise_rep_count: status === 'confirmed',
        specialized_form_correction: status === 'confirmed',
        hold_timing: false,
        general_guidance: status === 'confirmed',
      },
      coach_trigger: {
        triggered: status === 'confirmed',
        reason: status === 'confirmed' ? 'exercise_confirmed' : 'none',
        priority: status === 'confirmed' ? 'encouragement' : 'none',
        recommended_intent: status === 'confirmed' ? 'announce_exercise' : 'observe',
        report_id: 'test:1:1',
        cooldown_ms: 8000,
      },
    },
  };
}

describe('agent telemetry', () => {
  it('measures time to the first confirmed result', () => {
    let telemetry = accumulateAgentTelemetry(
      createAgentTelemetry(), response('unknown'), 1000, null,
    );
    telemetry = accumulateAgentTelemetry(
      telemetry, response('candidate'), 1300, null,
    );
    telemetry = accumulateAgentTelemetry(
      telemetry, response('confirmed', 'squat'), 1700, null,
    );

    expect(telemetry.firstConfirmedLatencyMs).toBe(700);
    expect(telemetry.unknownFrames).toBe(1);
    expect(telemetry.candidateFrames).toBe(1);
    expect(telemetry.confirmedFrames).toBe(1);
  });

  it('scores only confirmed frames when ground truth is supplied', () => {
    let telemetry = accumulateAgentTelemetry(
      createAgentTelemetry(), response('candidate', 'squat'), 1000, 'squat',
    );
    telemetry = accumulateAgentTelemetry(
      telemetry, response('confirmed', 'squat'), 1100, 'squat',
    );
    telemetry = accumulateAgentTelemetry(
      telemetry, response('confirmed', 'pushup'), 1200, 'squat',
    );

    const summary = summarizeAgentTelemetry(telemetry);
    expect(telemetry.evaluatedConfirmedFrames).toBe(2);
    expect(telemetry.correctConfirmedFrames).toBe(1);
    expect(telemetry.incorrectConfirmedFrames).toBe(1);
    expect(summary.confirmedAccuracy).toBe(0.5);
  });

  it('does not claim accuracy without a ground-truth label', () => {
    const telemetry = accumulateAgentTelemetry(
      createAgentTelemetry(), response('confirmed', 'squat'), 1000, null,
    );

    expect(summarizeAgentTelemetry(telemetry).confirmedAccuracy).toBeNull();
  });

  it('keeps an auditable per-response trace with relative timing', () => {
    let telemetry = accumulateAgentTelemetry(
      createAgentTelemetry(), response('candidate', 'squat'), 1000, 'squat',
    );
    telemetry = accumulateAgentTelemetry(
      telemetry, response('confirmed', 'squat'), 1350, 'squat',
    );

    expect(telemetry.trace).toHaveLength(2);
    expect(telemetry.trace[0]).toMatchObject({
      elapsedMs: 0,
      expectedExercise: 'squat',
      recognitionStatus: 'candidate',
    });
    expect(telemetry.trace[1]).toMatchObject({
      elapsedMs: 350,
      recognizedExercise: 'squat',
      recognitionStatus: 'confirmed',
    });
  });

  it('bounds the exported trace to 5000 responses', () => {
    let telemetry = createAgentTelemetry();
    for (let index = 0; index < 5002; index += 1) {
      telemetry = accumulateAgentTelemetry(
        telemetry, response('unknown'), index, 'unknown',
      );
    }

    expect(telemetry.frames).toBe(5002);
    expect(telemetry.trace).toHaveLength(5000);
    expect(telemetry.trace[0].elapsedMs).toBe(2);
  });
});

import { describe, expect, it } from 'vitest';
import { SubjectTracker, TrackLandmark } from './SubjectTracker';

function pose(centerX: number, centerY = 0.5, scale = 0.25): TrackLandmark[] {
  const landmarks = Array.from({ length: 33 }, () => ({
    x: centerX,
    y: centerY,
    visibility: 1,
  }));
  landmarks[11] = { x: centerX - scale / 2, y: centerY - scale / 2, visibility: 1 };
  landmarks[12] = { x: centerX + scale / 2, y: centerY - scale / 2, visibility: 1 };
  landmarks[23] = { x: centerX - scale / 3, y: centerY + scale / 2, visibility: 1 };
  landmarks[24] = { x: centerX + scale / 3, y: centerY + scale / 2, visibility: 1 };
  landmarks[27] = { x: centerX - scale / 3, y: centerY + scale, visibility: 1 };
  landmarks[28] = { x: centerX + scale / 3, y: centerY + scale, visibility: 1 };
  return landmarks;
}

describe('SubjectTracker', () => {
  it('locks the first single workout subject', () => {
    const tracker = new SubjectTracker();
    const result = tracker.select([pose(0.5)]);
    expect(result?.locked).toBe(true);
    expect(result?.index).toBe(0);
  });

  it('keeps the continuous subject when a bystander enters', () => {
    const tracker = new SubjectTracker();
    tracker.select([pose(0.35)]);
    const result = tracker.select([pose(0.37), pose(0.78, 0.5, 0.35)]);
    expect(result?.locked).toBe(true);
    expect(result?.index).toBe(0);
    expect(result?.warning).toContain('已锁定');
  });

  it('freezes rather than swapping identity during an ambiguous crossing', () => {
    const tracker = new SubjectTracker();
    tracker.select([pose(0.48)]);
    const result = tracker.select([pose(0.47), pose(0.49)]);
    expect(result?.locked).toBe(false);
    expect(result?.ambiguity).toBeGreaterThan(0.8);
  });

  it('requires stable evidence before locking a far replacement', () => {
    const tracker = new SubjectTracker();
    tracker.select([pose(0.2)]);
    expect(tracker.select([pose(0.8)])?.locked).toBe(false);
    expect(tracker.select([pose(0.8)])?.locked).toBe(false);
    expect(tracker.select([pose(0.8)])?.locked).toBe(true);
  });

  it('resets identity after an extended period without a detected pose', () => {
    const tracker = new SubjectTracker(0.22, 0.08, 3, 2);
    tracker.select([pose(0.2)]);
    tracker.noteMissing();
    tracker.noteMissing();
    expect(tracker.select([pose(0.8)])?.locked).toBe(true);
  });
});

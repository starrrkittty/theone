export interface TrackLandmark {
  x: number;
  y: number;
  visibility?: number;
}

export interface SubjectSelection {
  index: number;
  locked: boolean;
  ambiguity: number;
  warning: string | null;
}

interface Descriptor {
  index: number;
  center: { x: number; y: number };
  size: number;
  visibility: number;
  continuityDistance: number;
  score: number;
}

/**
 * Conservative primary-user tracker for video-call frames.
 *
 * It deliberately freezes on ambiguous crossings instead of silently moving a
 * workout session, repetition counter, or correction history to a bystander.
 * A far-away replacement must remain stable for several frames before the
 * tracker starts a new lock.
 */
export class SubjectTracker {
  private lastCenter: { x: number; y: number } | null = null;
  private lastSize: number | null = null;
  private missingFrames = 0;
  private pendingCenter: { x: number; y: number } | null = null;
  private pendingHits = 0;

  constructor(
    private readonly maxContinuityDistance = 0.22,
    private readonly minimumScoreMargin = 0.08,
    private readonly reacquireFrames = 3,
    private readonly resetAfterMissingFrames = 15,
  ) {}

  select(poses: TrackLandmark[][]): SubjectSelection | null {
    if (poses.length === 0) {
      this.noteMissing();
      return null;
    }
    this.missingFrames = 0;

    const descriptors = poses
      .map((pose, index) => this.describe(pose, index))
      .sort((left, right) => right.score - left.score);
    const best = descriptors[0];
    const second = descriptors[1];
    const margin = second ? best.score - second.score : 1;
    const ambiguity = second
      ? Math.max(0, Math.min(1, 1 - Math.max(0, margin) / 0.2))
      : 0;

    let locked = false;
    if (this.lastCenter === null) {
      locked = poses.length === 1 || (
        margin >= this.minimumScoreMargin && best.visibility >= 0.4
      );
    } else if (
      best.continuityDistance <= this.maxContinuityDistance
      && (!second || margin >= this.minimumScoreMargin)
    ) {
      locked = true;
    } else if (poses.length === 1) {
      locked = this.updateReacquisition(best.center);
    } else {
      this.clearReacquisition();
    }

    if (locked) {
      this.updateLock(best);
      this.clearReacquisition();
    }

    return {
      index: best.index,
      locked,
      ambiguity,
      warning: poses.length > 1
        ? locked
          ? `检测到${poses.length}人，已锁定主要锻炼者`
          : `检测到${poses.length}人，无法稳定锁定主要锻炼者`
        : locked
          ? null
          : '原锻炼者离开或画面跳变，正在重新锁定',
    };
  }

  noteMissing(): void {
    this.missingFrames += 1;
    this.clearReacquisition();
    if (this.missingFrames >= this.resetAfterMissingFrames) {
      this.reset();
    }
  }

  reset(): void {
    this.lastCenter = null;
    this.lastSize = null;
    this.missingFrames = 0;
    this.clearReacquisition();
  }

  private describe(pose: TrackLandmark[], index: number): Descriptor {
    const core = [11, 12, 23, 24]
      .map(joint => pose[joint])
      .filter((landmark): landmark is TrackLandmark => Boolean(landmark));
    const center = core.length
      ? core.reduce(
        (accumulator, landmark) => ({
          x: accumulator.x + landmark.x / core.length,
          y: accumulator.y + landmark.y / core.length,
        }),
        { x: 0, y: 0 },
      )
      : { x: 0.5, y: 0.5 };
    const visible = pose.filter(landmark => (landmark.visibility ?? 0) >= 0.3);
    const xs = visible.map(landmark => landmark.x);
    const ys = visible.map(landmark => landmark.y);
    const area = xs.length
      ? (Math.max(...xs) - Math.min(...xs)) * (Math.max(...ys) - Math.min(...ys))
      : 0;
    const visibility = core.reduce(
      (sum, landmark) => sum + (landmark.visibility ?? 0),
      0,
    ) / Math.max(core.length, 1);
    const centerDistance = Math.hypot(center.x - 0.5, center.y - 0.5);
    const continuityDistance = this.lastCenter
      ? Math.hypot(center.x - this.lastCenter.x, center.y - this.lastCenter.y)
      : centerDistance;
    const continuity = Math.max(0, 1 - continuityDistance / 0.35);
    const centered = Math.max(0, 1 - centerDistance / 0.7);
    const size = Math.min(1, Math.sqrt(Math.max(area, 0)) * 2.2);
    const sizeMatch = this.lastSize === null
      ? size
      : Math.max(0, 1 - Math.abs(size - this.lastSize) / 0.5);
    const score = this.lastCenter
      ? 0.65 * continuity + 0.15 * sizeMatch + 0.1 * size + 0.1 * visibility
      : 0.35 * centered + 0.3 * size + 0.35 * visibility;
    return { index, center, size, visibility, continuityDistance, score };
  }

  private updateLock(descriptor: Descriptor): void {
    if (this.lastCenter === null) {
      this.lastCenter = descriptor.center;
    } else {
      const alpha = 0.35;
      this.lastCenter = {
        x: this.lastCenter.x * (1 - alpha) + descriptor.center.x * alpha,
        y: this.lastCenter.y * (1 - alpha) + descriptor.center.y * alpha,
      };
    }
    this.lastSize = this.lastSize === null
      ? descriptor.size
      : this.lastSize * 0.65 + descriptor.size * 0.35;
  }

  private updateReacquisition(center: { x: number; y: number }): boolean {
    if (
      this.pendingCenter
      && Math.hypot(center.x - this.pendingCenter.x, center.y - this.pendingCenter.y) <= 0.08
    ) {
      this.pendingHits += 1;
      this.pendingCenter = center;
    } else {
      this.pendingCenter = center;
      this.pendingHits = 1;
    }
    return this.pendingHits >= this.reacquireFrames;
  }

  private clearReacquisition(): void {
    this.pendingCenter = null;
    this.pendingHits = 0;
  }
}

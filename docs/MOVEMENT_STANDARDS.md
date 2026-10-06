# Movement Detection and Form Evaluation Thresholds

## Policy

The system uses two different thresholds:

- **Rep detection envelope** is deliberately wider. Crossing it can register a
  movement cycle even when the user has not reached the coaching target.
- **Form evaluation target** is narrower. It determines when to give a depth or
  range-of-motion cue; it does not cancel an otherwise detected repetition.

Angles from a single camera are estimates. The numbers below are engineering
proxies for common coaching cues, not universal anatomical limits, medical
advice, or angle values prescribed by the cited sources. Camera view, body
proportions, mobility, exercise variation, and pose-estimation confidence can
change the measured angle. Low-confidence measurements should not produce a
form judgment.

## First Ten Scoped Movements

| Exercise | B specialist | A readiness | Form evaluation / feedback rule | Rep detection |
| --- | --- | --- | --- | --- |
| Bodyweight squat | `squat_form` | Core realtime | Bottom mean included knee angle <= 100 deg is a provisional proxy for approaching thigh-parallel depth. | Flex zone <= 126 deg; extend zone >= 134 deg. Count and form target are separate. |
| Goblet squat | `squat_form` | Semantic only | Qualitative: controlled, comfortable depth and knee path. Do not inherit bodyweight numeric target without review. | No A variant detector. |
| Sit-to-stand | `squat_form` | Not in current realtime set | Qualitative: seat height and user capacity determine range; no universal knee angle. | Needs seat/stand transition observations. |
| Standard push-up | `push_form` | Generic push-up module; not variant-aware | Bottom mean included elbow angle <= 100 deg is a provisional camera proxy; a reviewed standard-push-up numeric source is still needed. | Flex zone <= 126 deg; extend zone >= 134 deg. Regression variants are not distinguished. |
| Bent-knee push-up | `push_form` | Generic push-up module; regression not identified | Qualitative controlled, comfortable range and trunk control. ACE source is specific to this regression and gives no angle cutoff. | Shared generic push-up cycle only. |
| Forearm plank | `plank_form` | Core realtime hold | Trunk sag deviation <= 10 deg is a provisional camera proxy for controlled alignment. | Hold timer; no repetition. Existing >15 deg candidate alert is a project heuristic. |
| Bicep curl | `curl_form` | Core realtime | Existing active-arm included elbow angle <= 80 deg contraction cue; project heuristic, not research-derived. | Flex zone <= 108 deg; extend zone >= 122 deg. |
| Alternate bicep curl | `curl_form` | Core realtime | No B numeric target until A supplies the active arm for the current phase; compare sides only in matching phases. | A counts each arm independently (flex <= 108 deg; extend >= 122 deg). |
| Reverse lunge | `lunge_form` | Semantic only | No numeric form threshold. Compare same-phase sides only; 12 deg projected knee-deviation rule is an unvalidated observation heuristic. | No A counter. |
| Barbell bent-over row | `pull_form` | Semantic only | No numeric form threshold. Existing 35 deg shoulder-elevation trigger is an unvalidated observation heuristic. | No A counter. |

Threshold cards are returned in B's `measurement_review.threshold_profile`,
and their deterministic comparisons are exposed as `measurement_review.target_checks`.
Angle fields use the names emitted by the A-to-B adapter (for example,
`left_knee_flexion`), and phase matching uses B's normalized phase values.
Numeric proxy values are considered only when movement variant, phase, angle
definition, camera view and confidence meet the profile requirements. B's LLM
must not convert qualitative-only or observation-only entries into numeric
pass/fail claims.

`target_checks` uses `within_project_target`, `outside_project_target`, or
`insufficient_evidence` for numeric proxy targets. Unsupported numeric profiles
return `non_numeric_guidance`. These are deterministic project-proxy comparisons;
they are not accuracy scores or validated coaching judgments.

The squat and push-up detection values follow from their current A counter
settings (upper=150 deg, lower=110 deg) and 40% hysteresis bands. Curl values
come from the per-arm A counter settings. Detection envelopes accept a movement
cycle; evaluation targets determine coaching cues and do not cancel a counted
cycle. The remaining movements require new A-side observations before precise
cycle detection can be claimed.

## Source basis and limits

- ACE, [Bodyweight Squat](https://www.acefitness.org/resources/everyone/exercise-library/135/bodyweight-squat/): general setup and controlled-execution guidance. The page does not prescribe a universal camera-measured knee-angle cutoff.
- ACE, [Bent Knee Push-up](https://www.acefitness.org/resources/everyone/exercise-library/13/bent-knee-push-up/): variant-specific guidance for a knee-supported regression. It is not a universal elbow-angle standard for every push-up variation.
- ACE, [Front Plank](https://www.acefitness.org/resources/everyone/exercise-library/32/front-plank/): setup and controlled hold guidance.
- ACE, [Bent-over Row](https://www.acefitness.org/resources/everyone/exercise-library/12/bent-over-row/): barbell-row execution guidance; no shoulder-angle cutoff.
- ACE, [Anti-rotation Reverse Lunge](https://www.acefitness.org/resources/everyone/exercise-library/348/anti-rotation-reverse-lunge/): a specific cable variation, not a general lunge angle standard.
- NHS, [Strength exercises](https://www.nhs.uk/live-well/exercise/strength-and-flex-exercise-plan/strength-exercises/): source pointer for sit-to-stand guidance; retrieval failed in the current knowledge refresh, so it is not treated as reviewed evidence.
- The curl cue is currently an implementation heuristic; an approved, variant-specific coaching source and coach review are still needed.

The source links are public coaching references already recorded in
`coach/knowledge/sources.json`. ACE pages were fetched, but their summaries are
still marked for separate review in `coach/knowledge/fetch_manifest.json`; the
NHS page fetch failed. The numeric camera proxies and tolerances require
review by a qualified coach and evaluation on labeled videos from multiple
participants and camera placements before being described as validated.

## Calibration workflow

For each exercise, annotate the bottom/top phase and form target separately.
Measure false rep detections against the wide envelope, then measure coaching
cue precision/recall against the narrower evaluation target. Change the outer
detection envelope only when it causes missed or false repetitions; change the
evaluation target only with source review and coach agreement. Keep participant
identity isolated between calibration and final evaluation splits.

# A Agent Framework

Implemented 2026-10-03 in the combined project. The original A repository remains
unchanged. This document supersedes the earlier audit's missing-URDF/Agent status.

## Running Flow

Video -> MediaPipe image/world landmarks -> filtered geometry -> reduced skeleton
URDF snapshot -> urdf-parser-py plus strict topology/numeric validation -> parsed
structure and joint states -> recent motion JSON -> A evidence Agent -> B routing
and specialist Skills/knowledge -> coaching JSON.

The existing image classifier still proposes exercise/phase/counts in parallel.
The new URDF motion gate checks that proposal; the LLM cannot create a confirmed
label or change measured angles/counts. This is not a newly trained recognizer.

The fitter supplies left/right elbow and knee hinge proxies, observed proximal
transforms, median segment lengths (30 visible frames), visibility and FK endpoint
residuals. URDF is regenerated per frame: the shoulder/hip anchors are fitted fixed
transforms, not a stable full anatomical model. Missing limbs are omitted.

worldLandmarks are preferred, independently filtered, and recorded as
estimated_meters. They are learned 3D estimates, not externally calibrated metric
measurements. If unavailable/invalid, image coordinates are used, with explicit
non-metric units. Such an exported URDF needs unit conversion before robotics use.
No force, torque, muscle activation, load or medical risk is inferred.

## Agent and Skill

`coach/skills/perception-urdf/SKILL.md` is actually loaded into the model prompt.
The existing `coach/config.json` / FITNESS_API_KEY, FITNESS_BASE_URL, FITNESS_MODEL
configuration is shared by A and B. Mandatory inspections run locally and are
consolidated into an action-specific evidence packet. Normally A finishes in one
model call; ambiguity allows two extra inspections, at most three model calls.
It does not call the LLM at camera frame rate.

- inspect_urdf: parser topology, definitions, fit and current states.
- inspect_motion: up to six seconds / 120 frames of joint motion.
- inspect_visibility: observation quality, camera view and mandatory gates.
- inspect_recognition: candidate/confirmed label, phase and counts.

Outputs: observe, request_view or handoff. Every handoff requires URDF, visibility
and recognition inspection; dynamic exercises also require motion inspection.
The deterministic gate requires confirmed recognition, reliable pose, both
exercise-relevant limbs visible, and recent motion (five samples, >=0.4 seconds,
trimmed hinge range >=0.08 radians). Plank requires duration but no hinge movement.
These are configurable-in-code engineering gates, not published fitness norms.
Slow/shallow movement can remain unconfirmed. Model decisions can withhold a
handoff but cannot override a failed gate. A handoff never certifies good form.

No key: real-time local policy, URDF generation/parser/FK and JSON export work.
Configured key: model evidence review and A -> B expert processing are enabled.
`POST /api/agent-a/coach` performs A review first for new local-policy reports,
then calls the existing B specialist only when allowed. Old A reports retain
their existing B integration behavior.

Live reviews use immutable snapshots and a per-session concurrency guard, a
20-second interval for new model calls, reset generation checking, and freshness/exercise checks.
Reviews older than 15 seconds relative to live frames cannot trigger handoff.
Session snapshots expire after 10 seconds without frames. Source reset or tracking
loss clears motion/fit history. Historical JSON reviews are labelled historical.

## Context Optimization

Updated 2026-10-03. The packet contains only exercise-relevant joint definitions,
states, segment angles, visibility, recent motion, fit residuals and consistency
flags. It excludes XML, per-frame anchor transforms and prior Agent transcripts.
Topology/convention IDs remain stable across fitted origin changes; relevant
definitions are still supplied, since a stateless model cannot recall an ID.
Stable Skill/schema text is kept at the front for provider prefix caching when
available; no particular provider cache feature is assumed or required.

Extra tool results replace the prior variable evidence message rather than growing
an unlimited transcript. A bounded session summary holds the last decision and
observation request; it is historical context, not current measurement.
B movement prompts exclude duplicated context, URDF structure and A tool traces;
full reports/exports remain intact and retain scientific measurement limitations.

An A review can be reused for 45 seconds only while the evidence revision remains
unchanged. Exercise/status, camera, coordinate source, pose quality, joint
visibility bands, violations, recent ROM/bounds and disagreement flags invalidate
reuse. Tracking loss/reset also invalidates it, including loss followed by recovery.
Normal phase/rep count changes do not independently force A reassessment.
Reuse applies the prior decision to current gated observations and explicitly
records the original review timestamp, model_called=false and cache_hit=true.
B still evaluates the new measured input; its posture guidance is not cached.

Image/world angle disagreement >=25 degrees in at least five of the last eight
frames for required hinge joints now withholds handoff and requests a side view.
Older imported JSON without persistence metadata uses a conservative instantaneous
check. This engineering consistency gate does not prove
which estimate is correct and may increase abstentions. Real videos are needed to
calibrate it. Numeric changes are compared with an anchored profile using
0.2-rad motion and 0.15 confidence/visibility deadbands; categorical changes
invalidate immediately. These are engineering review triggers, not recommended
posture ranges or measured error probabilities.

The UI exposes model call count, total input characters, latency and provider token
usage when returned. Character counts are not token counts. No real API cost/speed
benchmark or real-video accuracy evaluation has been performed for this update.

## Interfaces

| Route | Purpose |
| --- | --- |
| GET /api/agent-a/status | Parser/backend/model state and connected sessions |
| GET /api/agent-a/sessions/{id} | Current report plus motion evidence |
| GET /api/agent-a/sessions/{id}/urdf | Download latest fitted URDF snapshot |
| POST /api/agent-a/sessions/{id}/review | Run A model tool loop on live evidence |
| POST /api/agent-a/review-json | Review exported ActionReport JSON; validate and reconstruct URDF first |
| POST /api/agent-a/urdf/parse | Parse urdf_xml and joint_positions (rotational radians / prismatic meters); return structure/FK |
| POST /api/agent-a/coach | A review -> B movement specialist |

The webpage adds an A perception panel with joint values, source, model review,
tool trace, URDF export and JSON downloads. Existing B report/planning/nutrition
workflows still require actual training records and personal context.

## Parser Choice

Uses urdf-parser-py 0.0.4, https://github.com/ros/urdf_parser_py . Its
URDF.from_xml_string does not need ROS. The source/metadata were inspected via
PyPI on 2026-10-03. Normal setup installs its lxml/PyYAML dependencies automatically.
The current host installs the verified pure-Python source in `.deps` using
`tools/install_urdf_parser.py`; its SHA256 is checked against the PyPI artifact.
If unavailable, a strict ElementTree parser is explicitly reported as fallback.

The parser alone has no video inference or inverse kinematics. Strict checks
reject DTD/entity declarations (ordinary XML comments are accepted), large XML, duplicate links/joints, disconnected
graphs/cycles, invalid roots, non-finite values, zero axes and reversed limits.
Our FK implementation uses NumPy and SciPy Rotation for fixed/revolute/continuous/
prismatic joints. Floating/planar joints are explicitly unsupported in this stage.
URDF limits are never interpreted as recommended exercise angles.

MediaPipe source terminology: https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker
and https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker/web_js .

## Completion Boundary

This is an implemented reduced perception Agent framework, not a validated full
body digital twin. Full shoulder/hip multi-axis anatomical calibration, robust
person tracking, camera/scale calibration and a trained temporal recognizer remain
unimplemented. These require measurement design and real labelled data.

On 2026-10-03 the updated integration passed 156 backend tests, 15 frontend tests,
TypeScript/production build and HTTP startup checks. Model integration tests use
explicit mocks. A 616-frame public skeleton replay exposed remaining recognition
and repetition failures; it does not validate RGB perception or model coaching.
See OPTIMIZATION_EVALUATION.md for the baseline, results and limitations.
A real API key is still absent.

The completed-set workflow now buffers timestamped landmarks and uses two passes
after capture ends. Confirmed segment evidence anchors retrospective recognition;
fresh exercise modules replay the segment from its start under an observation
clock, recovering cycles missed during online confirmation. A/B review happens
after local analysis and remains subject to evidence gates. Latest verification
is 167 backend and 15 frontend tests; the single development squat clip now counts
one complete repetition. See OPTIMIZATION_EVALUATION.md for limits and routes.

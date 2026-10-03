# Performance, model APIs and retained artifacts

## Runtime boundaries

| Stage | Runtime | Calls configured language model API? |
| --- | --- | --- |
| Video decoding and MediaPipe tracking | Browser, GPU or CPU | No |
| Skeleton validation/filtering, recognition and counting | Local Python | No |
| Reduced skeleton fitting, URDF parser, evidence gates | Local Python | No |
| Optional A evidence review | Configured Chat Completions service | Yes |
| B movement specialist, workout report, plan, nutrition | Configured Chat Completions service | Yes |

A language model API improves evidence interpretation and personalized wording
only if the selected model performs well. It cannot supply missing landmarks,
repair unobserved counts, or calibrate monocular joint angles automatically.
Use a text model with reliable structured JSON output and Chinese instructions.
See MODEL_CONNECTION.md for the existing key/base URL/model configuration.

## Where time goes

MediaPipe is designed for real-time tracking on suitable hardware. The previous
13-second video taking 52-61 seconds describes the entire deterministic offline
sampling workflow, not a measured model-only FPS. Offline seeking may repeatedly
decode frames from compressed keyframes, and Full/Heavy models trade speed for
capacity. Synchronous browser inference also competes with painting and React.

Live tracking now targets 20 FPS to match the existing transmission ceiling,
uses requestVideoFrameCallback where available, and adjusts its sampling interval
against an inference moving average. No older inference requests are queued.
This is an engineering speed control; it does not guarantee 20 measured FPS.
UI reports measured throughput, inference mean and backend recognition/kinematics
time. Sample intervals still come from actual observation timestamps.

Offline metrics separate model initialization, inference median/P95 and throughput,
and decoding/scheduling overhead. Set results separate recognition, segment
kinematics, sequence quality, optional diagnostic replay and optional Agent review.
As of 2026-10-03, offline capture defaults to fixed-time seek for reproducible
sample grids and accuracy inspection. Sequential playback remains optional;
it uses video frame callbacks and actual timestamps but can retain fewer frames.
Expected and retained sample counts are displayed separately. Unsupported
frame-callback browsers fall back to seek and report the actual capture mode.
Default trace is off: enabling it adds another measured replay plus large XML/JSON
outputs. Model latency and token usage remain available in generated Agent records.

## Redundancy changes

- Live browser requests opt into compact responses that omit repeated URDF
  structure/fit records. Full reports remain available through the session endpoint
  and the A download button. Legacy consumers receive full responses by default.
- Offline preview painting is limited to about 10 updates per second, while every
  requested sampled frame is still processed and retained.
  Per-frame setTimeout yielding is replaced with a MessageChannel task to avoid
  background timer clamping. Seek/decode and yield waits are now measured separately.
- B prompts remove past Agent execution records from historical reports and
  repeated violations/flags from set summaries. Preserve counts, symptoms, recovery
  notes, definitions, visibility, provenance and angle ranges. Stored reports stay
  complete; numeric token usage must come from the API response, not character counts.
- Removed one byte-identical generated evaluation file; its baseline is retained
  with the SHA256 recorded in OPTIMIZATION_EVALUATION.md.
- Original A source zip and unused agent-server logs are archived separately from
  the active source tree. Logs still held open by another server are retained.
- Replaced the unsupported "Great form!" label with a statement that no current
  rule was triggered; this is not a claim of verified correct posture.

Do not purge original RGB samples, independent references, configuration or user
history as redundant. Other running local servers may still hold old log files.

## Observed run, 2026-10-03

RepCount edited demo, Full/GPU, first two seconds sampled at 20 FPS (40 frames):
initialization 0.3 s, capture total 2.7 s, inference median 9.1 ms, P95 12.5 ms,
inference throughput including warmup 42.6 FPS, decode/scheduling about 1.4 s.
Backend recognition pass 128.0 ms, segment kinematics 240.2 ms, quality 3.6 ms,
total 371.8 ms. No LLM calls and no reference labels; this is performance evidence.

The full live playback with Full/GPU ended with displayed throughput 14.9 FPS,
inference moving average 10.5 ms, last backend recognition 4.0 ms and skeleton
evidence 5.1 ms. These are displayed recent-window values, not whole-run averages.
The sampled stream retained 168 frames. Live counting showed 4, completed replay
showed 2 and skipped 11 frames before the subsequent counting-quality change.
This exposed a real pipeline discrepancy; neither count is a validated ground truth.
Completed replay now separates visible-side squat counting confidence from whole
body form confidence and records skip reasons. Validate this change independently.

On a second live run after that change (201 retained frames), the displayed live
count was 4 and completed replay counted 3, with 16 unreliable counting frames
and 8 frames usable for counting only. Different sampled frames prevent claiming
a controlled improvement. Subsequently the counter preserves observed state
across at most 250 ms of rejected input at that historical stage. The 2026-10-03
revision retains pending state for 500 ms; longer gaps abandon the pending cycle
while preserving completed counts. Predictions do not trigger transitions.
This engineering policy requires independent cycle validation; see ACCURACY_AUDIT.md.

Full offline demo after counting changes, before MessageChannel replacement:
268 frames, no missing pose frames, 59.7 s capture total, inference median 13.4 ms,
P95 17.5 ms, inference throughput 61.2 FPS, decode/scheduling 55.1 s. Backend
two-pass analysis 3.34 s; six closed cycles, two rejected counting frames, no gap
resets. There is no independent count truth. This confirms model inference was
not the largest cost in that offline run, but does not isolate seek from timers.

Sequential-mode run of the same demo: capture 13.6 s, Full/GPU inference median
10.8 ms, P95 15.9 ms, inference throughput 69.1 FPS; 191 of 268 target samples
retained, no missing detections among retained frames, five closed cycles, five
rejected counting frames, one long-gap reset. Backend total 2.16 s. This reduces
capture latency but changes sampled evidence and count. The UI warns when retained
samples are below 90% of target density; this threshold is an engineering diagnostic,
not a recognition accuracy score. Use fixed-time mode to review affected counts.

## Further changes requiring measurement

Compare Lite/Full/Heavy on the same independently annotated footage. For hardware
that cannot maintain a useful rate, consider a Web Worker for UI responsiveness
(not automatically higher inference throughput), sequential WebCodecs decoding
with explicit format support, or an actual RTMPose backend with keypoint mapping.
MotionBERT can be evaluated for deferred temporal reconstruction. None of these
alternative runtimes has been integrated in this version. Larger models alone do
not resolve view ambiguity, occlusion, missing action training or angle calibration.

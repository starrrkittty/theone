# Architecture Optimization and Diagnostic Evaluation

Updated: 2026-10-03. This is an implementation and development diagnostic report,
not a release claim of validated exercise recognition or coaching accuracy.

## Completed-Set Update

Additional supported-action regressions now pass: 174 backend tests, 15 frontend
tests and production build. See OTHER_ACTION_TESTS.md for synthetic action/count
results and MODEL_CONNECTION.md for the local-detection versus model-API boundary.

The default expert workflow now buffers an observed set and analyzes it after the
user ends the set or stops capture. Real-time expert guidance remains optional.
The bounded capture holds 2,400 frames (about two minutes at 20 FPS); overflow and
rejected frames are reported. This is RAM storage and is lost on server restart.
At most eight disconnected sessions are retained for retrieval, with a 15-minute
expiry checked on access. Explicit reset clears captured data; stream discontinuity
resets live recognition but preserves the set buffer for separate segment replay.

A first pass finds confirmed supported movements and observation discontinuities.
A second pass assigns retrospective segments anchored by those confirmations and
feeds their earlier frames into fresh exercise modules. It does not relabel a fully
unknown set. Tracking loss/time gaps split segments. Poor-quality or incompatible
observations reset the in-progress rep cycle while preserving completed counts.
Mixed/unrecognized movements inside a continuous segment can still be assigned
incorrectly; an independent temporal classifier and labelled data remain needed.

Timing uses a thread/task-local observation clock from each frame timestamp, not
the speed of the offline computation. Existing live clocks fall back to normal
time outside a frame scope. Segment reports contain complete/partial repetitions,
source timestamps, skipped frames, image-proxy joint ranges and rule occurrences.
The last eligible representative URDF snapshot is reviewed by A, then B receives
the compact completed-set summary and the movement-report Skill. Raw frames are
not put in model prompts. Successfully completed expert results are reused on
retry; missing configuration preserves the local result. No batch feedback is
spoken as a live correction.

Routes:

| Route | Purpose |
| --- | --- |
| GET /api/agent-a/sessions/{id}/set | Capture status and last completed result |
| POST /api/agent-a/sessions/{id}/finish-set | Detach current frames, analyze, optionally invoke A/B |
| POST /api/agent-a/sessions/{id}/review-set | Retrieve/retry expert review of last completed set |
| POST /api/agent-a/analyze-set | Analyze an imported timestamped landmark sequence |

POST options use `{"include_agents":false}` for local-only analysis. Imported
requests additionally contain `session_id` and `frames`; each frame has a positive
millisecond `timestamp`, 33 `landmarks` (or zero for tracking loss), and optional
`world_landmarks`, `image_aspect_ratio`, `camera_view`, `client_probs`. Each landmark
has numeric `x`, `y`, `z`, `visibility`. Imported requests are bounded at 2,400 frames.
Two simultaneous local analyses are allowed; per-session finish/review requests
are serialized. The endpoint is independent of live evidence freshness because
its result is explicitly a completed-set assessment.

Latest diagnostic: ten clips yielded one squat segment and nine unknown decisions.
The squat has 28 online-confirmed frames, while all 73 observed frames are replayed
within the completed segment. Its count changed from zero to one, matching the
clip reference. This is **not 100% real-time recall** or independent generalization
validation. Results: `evaluation/public_sample_completed_sets.json`. Reproduce:

```powershell
python tools/evaluate_completed_sets.py evaluation/public_sample.json --output evaluation/public_sample_completed_sets.json
```

Latest verification: 167 backend tests, 15 frontend tests and production build
passed. New coverage includes complete-set replay, scoped observation time,
static abstention, tracking loss, bounded buffering, disconnect/finish, failure
recovery, imported input validation and explicit mock A/B Skill integration.
The webpage's completed-set entry was confirmed through browser inspection.
A real API key is still absent; no actual model coaching quality was evaluated.

## Implemented Changes

- Online WebSocket and offline replay share `perception/pipeline.py`: recognition,
  report construction, fitted URDF parsing, motion evidence and handoff policy.
- Generated URDF comments are accepted; DTD/entities remain prohibited. This fixes
  a live processing crash when a reliable fitted skeleton first became available.
- Stream gaps over 750 ms or non-increasing timestamps reset recognition filters,
  temporal evidence, rep modules, report history and perception generation together.
  Counts start a new observation segment; interrupted reps are not inferred.
- Browser transmission is capped at 20 FPS before serialization. Disconnected
  frames retain only the newest pending frame. Stale/out-of-order responses and
  events from replaced sockets are ignored. Duplicate session ownership is rejected.
- A normally uses one model request, with at most three for additional inspection.
  Local tools compute mandatory checks. Only relevant joint evidence is sent;
  additional tool results replace the variable message rather than expanding history.
- An unchanged A review can be reused for 45 seconds. Anchored numeric deadbands
  reduce cache chatter; quality, exercise, coordinate and policy changes invalidate
  it. New calls have a 20-second minimum interval. Cached decisions are reapplied to
  current measured evidence with original review provenance.
- B receives compact observations without repeated URDF structures or A transcripts.
  Full exports retain the original evidence and measurement limitations.
- Skill and knowledge resources use bounded caches with file modification/size
  invalidation. Retrieved records are copied before returning to avoid mutation.
- Real model requests share a two-slot concurrency limit and bounded input/output.
  Busy calls fail after a short queue wait; transport errors always release capacity.
- Coaching has a per-session lease. A result cannot authorize handoff after session
  reset or evidence revision. B results that become stale during inference are marked
  historical; the browser does not speak them as current corrections.
- Known exercise signal quality uses its relevant joints, avoiding double penalties
  from missing face/finger points. Plank has its own joint weights.
- Alternate curl requires both elbows to move with opposite temporal correlation;
  asymmetry alone is insufficient. Dominant shoulder/knee motion and raised upper
  arms cause abstention for the supported upright curl variants. Bilateral squat
  requires both visible knees to move with sufficiently similar current angles.

Recognition values (12-degree motion, 30-degree knee asymmetry, 65-degree raised
upper arm and -0.25 correlation), cache deadbands and conflict thresholds are
engineering heuristics. They are not scientific recommendations for joint posture.
They may reject valid unilateral, occluded or nonstandard exercise variants.

## Small Public Sample

Source: UI-PRMD mirror, ten clips, one subject and one trial per movement,
616 frames. Pinned revision:
`d69141abc6743644bc2fcc12e42ca7825587c3c6` of
https://github.com/tejas1904/UI-PRMD-Visualize-python-port .
`evaluation/public_sample_manifest.json` records URLs, SHA256 hashes and assumptions.

The official download was unavailable during this session. The mirror has no
explicit dataset license; authorization/redistribution rights remain unverified.
Downloaded raw and derived samples are local research artifacts excluded by
`.gitignore`. Do not treat them as a licensed training distribution.

The adapter reconstructs 22-joint local offsets with xyz Euler rotations and maps
them to 33 landmarks. Reconstruction has not been checked against the official
loader. Mapped visibility=1 is an assumption, not measured tracking confidence.
Image framing is derived across these clips; no world-landmark input or RGB
perception was evaluated. Any reconstruction error can change recognition results.

Deep squat is the only supported positive class (73 frames). The other nine labels
test abstention (543 frames), not form correctness. Clip labels are propagated to
frames and are not phase annotations. These clips informed development, so the
second evaluation is not held-out validation.

## Diagnostic Results

| Metric | Before recognition fixes | After recognition fixes |
| --- | ---: | ---: |
| Unsupported-action false-positive frames | 76/543 (14.0%) | 0/543 (0%) |
| Squat confirmed-frame recall | 0/73 (0%) | 28/73 (38.4%) |
| Correct among all confirmed frames | 0/76 (0%) | 28/28 (100%) |
| All-frame recognition coverage | 12.3% | 4.5% |
| Deep-squat rep count / clip reference | 0 / 1 | 0 / 1 |
| Locally permitted handoff frames / valid B schemas | 70 / 70 | 28 / 28 |
| Local measured pipeline p50 | 5.69 ms | 6.22 ms |
| Local measured pipeline p95 | 13.29 ms | 12.36 ms |
| Local measured pipeline p99 | 15.75 ms | 14.43 ms |

The baseline already includes earlier architectural optimizations; this comparison
isolates the subsequent recognition changes approximately, not the entire project.
Timing is one CPU replay run and excludes RGB inference, network, browser rendering,
model requests and speech. Median did not improve; no end-to-end speedup is claimed.

After changes, average compact evidence is 1,130 characters versus 2,207 for the
full report, about 49% smaller. This compares two representations within the latest
replay, not total model prompt lengths or billable tokens. Recognition changes also
change report contents, so cross-version mean sizes are not a fixed-input benchmark.

Overall frame accuracy is 92.7%, dominated by unknown frames. Even predicting
unknown everywhere would score 88.1%. Confirmed precision of 100% involves only
28 correlated frames in one positive clip. Neither number establishes production
accuracy. The positive clip's majority label is still unknown, and its count fails.

## Reproduction

From this project directory, using a Python environment with its dependencies:

```powershell
python tools/prepare_public_sample.py
python tools/replay_evaluation.py evaluation/public_sample.json --output evaluation/public_sample_optimized.json --full-chain
python -c "import os,sys; os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'; sys.path[:0]=['.deps','backend','coach']; import pytest; sys.exit(pytest.main(['backend/tests','-q','-p','no:cacheprovider','-p','pytest_asyncio.plugin']))"
```

From `frontend`:

```powershell
node node_modules/vitest/vitest.mjs run --config vitest.local.config.mjs
./build-local.ps1
```

Retained results: `evaluation/public_sample_baseline.json` and
`evaluation/public_sample_optimized.json`. The initial diagnostic run named
`public_sample_full_chain.json` was byte-identical to the baseline (SHA256
6821b2b93de85b87a711bc55402b43b3ce9fbb7ec1f90f635f1639cfaf2790aa);
the redundant copy was removed. Use `public_sample_baseline.json` for that run.

Verification: 156 backend tests, 15 frontend tests, TypeScript build, production
bundle and local HTTP startup passed. Regression tests cover compact evidence,
cache invalidation/provenance, resource reload, model capacity release, competing
motion, stream reset, duplicate session ownership and reset during A/B inference.
A-to-B specialist/report/planning integration tests use explicit mock models.

## Remaining Work

1. Verify skeleton conversion against the authoritative dataset loader before
   interpreting these angles as reference measurements.
2. Obtain independent labelled RGB clips from several participants, with camera
   views, occlusion, supported and unsupported movements, rep phases and counts.
   Evaluate subject-separated recognition, abstention and rep errors.
3. Replace or supplement heuristic recognition with a trained temporal recognizer.
   Knee flexion alone cannot reliably separate squat, lunge and sit-to-stand.
   Conservative abstention is a mitigation, not a complete classifier.
4. Validate counts on complete observed repetitions. This sample still fails the
   deep-squat count; warm-up, gating and interrupted observations can lose cycles.
5. Configure an actual model API and evaluate specialist conclusions, evidence
   fidelity, knowledge citations, reports/plans, latency and provider token usage.
   A key is absent; no real model quality or cost benchmark was performed.
6. Full anatomical shoulder/hip calibration, stable body model, camera calibration
   and robust person tracking remain outside the implemented four-hinge proxy model.

The integration can be exercised locally and the model connection is ready for
configuration. An API key enables reasoning; it does not repair uncertain pose,
untrained recognition or missing observation evidence automatically.

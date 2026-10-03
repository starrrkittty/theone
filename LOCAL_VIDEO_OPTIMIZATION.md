# Local video processing

The optimized service is available at http://127.0.0.1:8802/.

Select a local video in the offline analysis section. Choose Lite, Full or Heavy,
sampling rate, and optional start/end seconds. Full is the default for offline
processing; live playback retains Lite by default and also allows model selection.
Files are decoded in the browser using a local object URL; RGB video is not sent
to a cloud service. MediaPipe models and WASM still require their CDN assets on
first use. GPU initialization falls back to CPU on failure.

Offline processing seeks each requested video time, waits for decoding, then runs
pose inference before advancing. It does not use elapsed processing wall time as
the observation clock and does not discard frames when inference is slow.
Explicit no-pose frames remain in the capture. Decode/inference failures stop the
run instead of silently presenting a complete capture. Cancellation is supported
between model calls. Cancellation during model loading takes effect after loading.

The API accepts at most 2400 frames per run: 120 seconds at 20 FPS, 80 seconds at
30 FPS, 240 seconds at 10 FPS, or 480 seconds at 5 FPS. Longer files require an
explicit interval. Low frame rates can miss fast movement; long intervals must
not be claimed as complete real-video validation by reducing the rate silently.

Capture is retained in browser memory after extraction. Reanalyze cached frames
to retry backend/Agent requests. Download the raw capture separately from analysis
artifacts. With per-frame artifacts enabled, the analysis export contains inputs,
filtered points, ActionReports, URDF XML, parsed kinematics, policy, timings, and
completed-set summaries. Large trace exports increase response size and runtime.

Backend changes:

- Batched Kalman updates replace the per-landmark loop and matrix inverse.
- Joseph covariance update improves numerical stability.
- Sequence quality summaries expose no-pose fraction, timestamp discontinuities,
  joint visibility, degenerate segments, raw angle ranges and rapid angle changes.
- Trace replay shares the same processing function as live input and is bounded
  by the existing two-worker analysis limit.

Measurement diagnostics are descriptive. They do not prove anatomical accuracy
or automatically relax recognition thresholds. Existing action recognition still
uses the HMM/rule pipeline; no newly trained TCN or full-body action weights are
claimed. A trained temporal recognizer requires labeled real sequences, subject
separation, similar-motion negatives, and independent validation.

Optional expert review calls the existing configured A/B model clients after the
measured set is complete. No key is required for pose extraction, local action
analysis, URDF or JSON export. A configured key is required for model Agent review.

Implementation check: TypeScript compilation and production build completed.
Real-video comparison and model asset loading remain to be exercised with user
videos. No accuracy improvement has been measured for Lite/Full/Heavy yet.

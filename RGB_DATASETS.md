# RGB video evidence and datasets

## Actual input path

Camera/local video -> MediaPipe pose model -> landmark time series -> filtering,
action recognition and cycle counting -> reduced URDF and joint-state JSON ->
evidence gate -> optional A review -> B specialist feedback.

The diagnostic gallery's skeleton fixtures bypass video inference and are now
explicitly named skeleton replay. Their results cannot measure the first stage.
The offline page shows original footage and the actual video model overlay.

## Sources inspected

- Penn Action: https://dreamdragon.github.io/PennAction/
  2326 sequences, 15 actions, RGB frames, 13 annotated 2D joints, visibility,
  viewpoint and train/test labels. Includes squats and push-ups. It can evaluate
  2D pose and action recognition, but not calibrated 3D anatomical angles or
  exercise safety. RGB frame sequences need conversion to videos with explicit
  timing; invented FPS must not be used as real repetition timing ground truth.
- RepCount: https://svip-lab.github.io/dataset/RepCount_dataset.html
  RGB repetition videos and cycle locations/counts. Official downloads are
  hosted on OneDrive/Baidu. Part B original videos are not released, per the
  authors' repository. Use matching original clip annotations, not annotations
  from another split or a presentation GIF.
- Fitness-AQA: https://github.com/ParitoshParmar/Fitness-AQA
  Back squat, overhead press and barbell row form error data. Access requires
  an application and agreement to non-commercial terms. No access request was
  submitted. Loaded back squat must not be silently relabeled as bodyweight squat.

## Prepared local demonstration

The RepCount official `figures/squat.gif` at revision
`68bdd4daa60ed7c3174a7f6bf86f6537b6fa0979` was fetched and re-encoded as MP4,
preserving the GIF's presentation timing. This is compressed, edited RGB
demonstration footage, not a verified annotated dataset sample.

Run `tools/prepare_rgb_demo.py` to reproduce. URL, SHA256 and scope are recorded
in `frontend/public/datasets/manifest.json`. The video is available from the
offline panel's RepCount demo button. Raw/downloaded assets remain local and
are excluded from Git. No redistribution rights are inferred from public access.

The official repository's `open_set/new_train.csv`, `new_valid.csv` and
`new_test.csv` were also fetched (646, 128 and 250 rows). These are open-set
annotations, not a complete verified RepCount-A benchmark. In particular the
downloaded test CSV contains sit-up and bench-press labels; it is not squat truth.
No annotation was assigned to the GIF and no benchmark accuracy is claimed.

## Issues exposed by real video

Initial Full/GPU processing sampled 268 frames with no missing pose frames,
but required 61.1 seconds including extraction/model startup. This confirms
the path executes, not that live processing reaches 20 FPS on this machine.
The run recognized squat but rejected six cycles as partial. The far-side leg
had weaker visibility and biased bilateral averaging; squat now selects a
stable visible-leg counting proxy when visibility differs. The counter also
measured only the flex-to-extension interval against whole-cycle duration
limits; cycle timing now begins when leaving extension. Rejected-cycle
diagnostics expose duration, extrema, visibility and the rejection reason.
The squat detector's arbitrary one-second duration minimum was replaced by a
0.4-second debounce limit, consistent with the general counter default. Counting
an observed cycle does not certify appropriate tempo or acceptable technique.

These are development-driven fixes from a single demonstration. Independent
real-video verification across views, people, tempo and negative actions remains
necessary. Corrected counts must not be called benchmark accuracy.

## Long sessions and views

Live capture has a 2400-frame bound. Automatic splitting waits for a completed
rep after 1800 frames where possible, or forces splitting by 2250 frames. Forced
splits may leave partial cycles; histories retain only the last 20 analyzed sets.
Model prompts use existing compact measured evidence, not the entire session.

Time-aware Kalman prediction uses observation timestamps; hidden points are
predicted instead of treated as reliable measurements. A visible-leg count does
not establish bilateral symmetry. Side/unknown views suppress bilateral squat
form claims. Generic fixed-angle depth and forward-lean prescriptions were
removed from the squat module; measured angles remain available to reviewers.

Single-camera world landmarks are learned estimates. Reliable metric 3D angles
require external validation and, for multi-camera fusion, synchronization and
camera calibration. The current system does not implement calibrated multi-camera
triangulation or claim accuracy across every viewing angle.

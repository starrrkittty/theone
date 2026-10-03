# Pose research and implemented observation protocols

## Official sources consulted

- MediaPipe Pose Landmarker: https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker
  Detection plus pose tracking; 33 image/world landmarks; Lite/Full/Heavy variants.
  Already used in this application in VIDEO mode. World coordinates are learned
  monocular estimates, not calibrated anatomical ground truth.
- RTMPose: https://github.com/open-mmlab/mmpose/tree/main/projects/rtmpose
  Paper: https://arxiv.org/abs/2303.07399
  Mature 2D pose deployment options. Published COCO AP and hardware FPS do not
  establish fitness angle accuracy on this machine. A future adapter must map its
  keypoint convention, preserve missing joints, and never fabricate world points.
- MotionBERT: https://github.com/Walter0807/MotionBERT
  Paper: https://arxiv.org/abs/2210.06551
  Sequence-based 2D-to-3D motion reconstruction; requires upstream 2D poses and
  H36M-format mapping. Candidate for deferred review, not a direct RGB detector.

No RTMPose/MotionBERT runtime or weights have been integrated. The named Motion
Tracker project has not been identified as a specific published paper.

## Implemented changes

The backend owns exercise/view protocols; the browser displays this catalog.
Protocol selection does not provide expected exercise labels to recognition.
Observed view is voted over a bounded 600 ms window. Unknown/unsupported view
blocks expert handoff for the new profile, while counting remains independent.
Profile observations can use one reliably visible hinge for handoff, except for
alternating curls, which require both arms. Occluded hip landmarks no longer
prevent a valid visible-side reduced skeleton: a single visible hip may anchor
the coordinate system, explicitly labeled as not the pelvis center.

JSON and compact A evidence include declared/estimated views, supported
observations and limitations; the B adapter preserves this metadata. A and B
skills prohibit bilateral claims from profile views and depth claims from front
views. Existing measured angles and counts are not rewritten by the Agents.

Offline video capture separates model initialization, inference median/P95,
inference-only throughput and decoding/scheduling time. Compare Lite/Full/Heavy
on identical RGB intervals with independent landmark annotations before choosing
a replacement. These metrics describe performance, not recognition accuracy.

## Validation still needed

View inference remains heuristic and may confuse rotation, occlusion or unusual
body proportions. Filming guidance is an engineering observation protocol, not a
clinical standard. Single-hip anchoring changes the coordinate origin and must
not be interpreted as pelvis translation. Form rules and counting may still
abstain with poor visibility. A1/A2/B require independent references as described
in FRONTAL_STAGE_EVALUATION.md; no new accuracy benchmark is claimed here.

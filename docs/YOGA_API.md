# Yoga Mode — Standalone Integration Guide

Everything needed to build a **yoga-only** form-checking client against this backend, with no
dependency on the exercise/rep-counting pipeline.

- Production base: `https://exercise-form-backend.onrender.com`
- Production WebSocket: `wss://exercise-form-backend.onrender.com/api/ws/yoga/{client_id}`
- Local base: `http://localhost:8000`
- Local WebSocket: `ws://localhost:8000/api/ws/yoga/{client_id}`

---

## 1. What This Mode Is

Yoga poses are **held**, not repeated. So the yoga pipeline answers one question per frame:

> *Is the body in the selected pose right now, how long has it been held, and what should be fixed?*

That is a fundamentally different job from the exercise mode, which classifies an unknown
movement and counts flex–extend cycles. The two run as **completely separate pipelines** that
share only landmark geometry helpers.

| | Exercise mode | Yoga mode |
| --- | --- | --- |
| Endpoint | `/api/ws/pose/{client_id}` | `/api/ws/yoga/{client_id}` |
| Which movement? | Inferred by an HMM classifier | **Explicitly sent by the client** every frame |
| Scoring unit | Reps (Schmitt-trigger counter) | Continuous hold seconds |
| Session object | `FormManager` | `YogaManager` |
| Warm-up cost | ~60 frames to classify | **None** — feedback on frame 1 |
| Sequencing | n/a | Client-side; the backend is stateless about it |

**A standalone yoga app never touches the classifier.** There is no "detecting…" phase, no
confidence gate before feedback starts, and no risk of the pose being misidentified as a squat.

### Architecture

```text
Your app (browser / mobile webview)
│
├── Camera  ── getUserMedia ────────────────────────────────────┐
├── MediaPipe PoseLandmarker (client-side WASM, GPU)            │
│     └── 33 landmarks {x, y, z, visibility}                    │
│                                                                ▼
├── WebSocket ──────────────────────► /api/ws/yoga/{client_id}
│     send { landmarks, pose, timestamp }      │
│                                              │  BaseYogaPose.evaluate()
│                                              │  HoldTimer.update()
│     ◄──────────────────────────────────────  ┘
└── Render: skeleton + joint_colors, hold ring, correction text, voice cue
```

**No video pixels ever leave the device.** Only 33 floats-per-joint per frame. All computer
vision happens in the browser; the backend does geometry and timing only.

---

## 2. Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `WS` | `/api/ws/yoga/{client_id}` | The per-frame pose stream |
| `GET` | `/api/yoga/poses` | Pose catalog — labels, display names, camera view, target holds |
| `GET` | `/api/yoga/health` | Yoga-scoped health + connection count (use this for cold-start warm-up) |
| `POST` | `/api/reset/yoga/{client_id}` | Restart the current hold, keeping the selected pose |
| `GET` | `/docs` | FastAPI Swagger UI |

A yoga-only client needs **nothing else**. `/api/health`, `/api/exercises`, and the upload
endpoints all belong to the exercise mode.

### `client_id` rules

- Max 80 characters (`MAX_CLIENT_ID_LENGTH`)
- Must match `^[A-Za-z0-9_.:-]+$`

A violation closes the socket with code `1008` and reason `Invalid client_id`. Use a stable
per-user id if you have one, otherwise a generated UUID. **No authentication is required.**

### `GET /api/yoga/poses`

```json
{
  "poses": [
    {
      "label": "mountain",
      "display_name": "Mountain Pose",
      "sanskrit": "Tadasana",
      "camera_view": "front",
      "target_hold_seconds": 15.0
    }
  ]
}
```

Fetch this at startup and build your pose picker from it rather than hard-coding labels — the
catalog is the contract, and a `label` that is not in it will be rejected by the WebSocket.

---

## 3. WebSocket Protocol

### Client → Server (one message per frame)

```json
{
  "landmarks": [
    { "x": 0.5, "y": 0.3, "z": -0.1, "visibility": 0.99 }
  ],
  "pose": "tree",
  "timestamp": 1778390000000
}
```

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `landmarks` | array of 33 objects | **Yes** | MediaPipe pose topology, indices 0–32. `x`/`y` normalized 0–1; `y` grows **downward**. `visibility` 0–1. A missing or empty array makes the frame silently skipped — no response is sent. |
| `pose` | string | Effectively yes | A `label` from `/api/yoga/poses`. Send it on **every** frame; it is idempotent. Until a valid pose arrives the manager stays `idle`. |
| `timestamp` | number | No | Echoed back verbatim. Use it to match responses to frames and to measure round-trip latency. Defaults to `0`. |

Unknown extra keys are ignored.

**Send `pose` every frame.** `set_pose` returns immediately when the label is unchanged, so
there is no cost, and it means a reconnect (which creates a fresh `YogaManager`) recovers on the
very next frame without any extra handshake.

### Server → Client (one response per accepted frame)

```json
{
  "state": "holding",
  "current_pose": "tree",
  "pose_display": "Tree Pose",
  "camera_view": "front",
  "is_in_pose": true,
  "hold_seconds": 7.42,
  "hold_target_seconds": 20.0,
  "hold_progress": 0.371,
  "hold_complete": false,
  "just_completed": false,
  "violations": [],
  "corrections": [],
  "correction_message": "Hold steady — breathe",
  "joint_colors": { "left_knee": "green", "left_ankle": "green" },
  "confidence": 0.94,
  "timestamp": 1778390000000
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `state` | `"idle" \| "adjusting" \| "holding"` | `idle` = no pose selected (or an unknown label was sent). `adjusting` = pose selected, body not yet correct. `holding` = body is in the pose this frame. |
| `current_pose` | string \| null | The locked-in pose label; `null` while `idle`. |
| `pose_display` | string | Human-readable name, e.g. `"Tree Pose"`. |
| `camera_view` | `"front" \| "side"` | The view this pose needs. Drive a "turn your phone sideways" hint from it. |
| `is_in_pose` | bool | Frame-level verdict. `true` exactly when `violations` is empty. |
| `hold_seconds` | float | Wall-clock seconds of the current continuous hold. |
| `hold_target_seconds` | float | The pose's target (see catalog). |
| `hold_progress` | float | `min(1, hold_seconds / target)` — drive a progress ring from this. |
| `hold_complete` | bool | Target reached and still held. Stays `true` for the rest of the hold. |
| `just_completed` | bool | `true` on the **single frame** the target is first reached. Fire your chime / haptic / advance-the-flow here. |
| `violations` | string[] | What is wrong, e.g. `["Standing leg is bent"]`. |
| `corrections` | string[] | Actionable fixes, parallel to `violations`, e.g. `["Straighten and root down through your standing leg"]`. |
| `correction_message` | string | The one line to show/speak. See the precedence table below. |
| `joint_colors` | `{ [joint: string]: "green" \| "yellow" \| "red" }` | Snake_case joint names (`left_knee`, `right_shoulder`, …) matching `JointName` in `backend/exercises/base.py`. Colour your skeleton overlay with it. |
| `confidence` | float | Mean visibility of the pose's required joints (0–1). Below ~0.5, treat feedback as unreliable and prompt for better framing. |
| `timestamp` | number | Echoed from the client frame. |

#### `correction_message` precedence

| Condition | Message |
| --- | --- |
| No pose selected | `"Select a pose to begin"` |
| `hold_complete` | `"Great hold — pose complete!"` |
| Not in pose, has corrections | The first entry of `corrections` |
| Not in pose, no corrections | `"Move into the pose"` |
| In pose, target not reached | `"Hold steady — breathe"` |

#### Special responses

**Body not fully visible** — if any joint the pose requires is missing or below
`VISIBILITY_THRESHOLD` (`0.3`), the pose detector short-circuits before evaluating geometry:

```json
{
  "state": "adjusting",
  "is_in_pose": false,
  "violations": ["Body not fully visible"],
  "corrections": ["Step back so your whole body is in the camera frame"],
  "joint_colors": {},
  "confidence": 0.0
}
```

Treat this as a **framing problem, not a form problem** — surface "step back", never "your knee
is wrong".

**Unknown pose label** — a `pose` value that is not in the catalog returns `state: "idle"`,
`current_pose: null`, and `correction_message: "Unknown pose '<label>'"`. The connection stays
usable; send a valid label on the next frame and it recovers.

---

## 4. Session Lifecycle

```text
                     pose field with a valid label
  ┌────────┐  ───────────────────────────────────────►  ┌────────────┐
  │  idle  │                                            │ adjusting  │
  └────────┘  ◄───────────────────────────────────────  └────────────┘
       ▲       unknown label / no pose ever sent            │      ▲
       │                                      is_in_pose    │      │  is_in_pose false
       │                                                    ▼      │  past debounce
       │                                            ┌──────────────┴─┐
       └────────────────────────────────────────────│    holding     │
                    connection closed                └────────────────┘
                                                       hold_seconds ↑
                                                 target reached → just_completed (1 frame)
                                                                 → hold_complete (latched)
```

- One `YogaManager` per **WebSocket connection**, held in memory. Disconnect = state gone.
- Switching the `pose` field mid-stream **always starts a fresh hold** — a flow transition or a
  manual pose change never carries over the previous pose's accumulated time.
- `POST /api/reset/yoga/{client_id}` restarts the hold but **keeps the selected pose**. It
  returns `{"status": "not_found"}` if that client has no live connection.

### Hold timing semantics

`HoldTimer` (`backend/pipeline/hold_timer.py`) is the yoga analogue of the rep counter:

- Timing is **wall-clock** (`time.time()`), so it is independent of your frame rate. Dropping
  from 15 fps to 5 fps does not slow the hold down — it only makes feedback coarser.
- A **debounce window** absorbs MediaPipe jitter: up to `YOGA_HOLD_DEBOUNCE_FRAMES` (default
  `10`) consecutive not-in-pose frames are tolerated and the hold keeps running. The first miss
  *beyond* that window resets the hold to zero.
- At ~12 fps the default debounce is roughly **0.8 s of grace**. If you stream slower, lower the
  frame count or the grace window becomes uncomfortably long.
- `just_completed` is latched — it is `true` for exactly one frame per hold. Do not drive UI
  state off it without also handling `hold_complete` for late-joining renders.

---

## 5. Pose Catalog

Eight poses. Standing poses expect a **front-facing** camera; floor poses expect a **side** view.

| Label | Display | Sanskrit | View | Target hold | Checks |
| --- | --- | --- | --- | --- | --- |
| `mountain` | Mountain Pose | Tadasana | front | 15 s | Legs straight, torso vertical, shoulders level |
| `tree` | Tree Pose | Vrksasana | front | 20 s | One foot lifted, standing leg straight, balance held |
| `warrior_i` | Warrior I | Virabhadrasana I | front | 20 s | Front knee ~90°, back leg straight, torso upright, **both arms overhead** |
| `warrior_ii` | Warrior II | Virabhadrasana II | front | 25 s | Front knee ~90°, back leg straight, **arms extended wide and level** |
| `chair` | Chair Pose | Utkatasana | front | 20 s | Both knees bent, arms raised overhead |
| `triangle` | Triangle Pose | Trikonasana | front | 20 s | Legs straight, lateral hinge from the hip, arms in one vertical line |
| `downward_dog` | Downward Dog | Adho Mukha Svanasana | **side** | 20 s | Hips highest point, arms straight, legs straight, clean hip pike |
| `cobra` | Cobra Pose | Bhujangasana | **side** | 15 s | Chest lifted off the floor, hips and thighs grounded |

### Thresholds

All thresholds are **class constants** on the pose modules in
`backend/exercises/yoga_poses.py`, so they are easy to retune against real footage without
touching the pipeline. Angles are degrees; distances are normalized image units (0–1).

| Pose | Constants |
| --- | --- |
| `mountain` | `MIN_LEG_STRAIGHT=160`, `MAX_TORSO_TILT=15`, `MAX_SHOULDER_UNLEVEL=0.08` |
| `tree` | `STANDING_LEG_STRAIGHT=150`, `MIN_FOOT_LIFT=0.12`, `MAX_TORSO_TILT=22` |
| `warrior_i` / `warrior_ii` | `FRONT_KNEE_MIN=80`, `FRONT_KNEE_MAX=130`, `BACK_LEG_STRAIGHT=150`, `MAX_TORSO_TILT=30` |
| `warrior_ii` (extra) | `ARM_LEVEL_TOLERANCE=0.12`, `MIN_ARM_SPAN=0.45` |
| `chair` | `KNEE_BENT_MIN=70`, `KNEE_BENT_MAX=150` |
| `triangle` | `LEG_STRAIGHT=150`, `MIN_LATERAL_TILT=30`, `MIN_ARM_VERTICAL_GAP=0.30` |
| `downward_dog` | `HIPS_ABOVE=0.05`, `ARM_STRAIGHT=150`, `LEG_STRAIGHT=150`, `PIKE_MIN=30`, `PIKE_MAX=120` |
| `cobra` | `MIN_CHEST_LIFT=0.08`, `MAX_BODY_TILT=0.15`, `FLOOR_Y=0.55` |
| all | `VISIBILITY_THRESHOLD=0.3` |

**Detection reliability.** Standing poses are solid from a front camera at 2–3 m. Floor poses
(`downward_dog`, `cobra`) are the weak spot: phone-camera pose estimation of a body near the
floor is noisy, so their thresholds are deliberately lenient and their feedback is coarser.
Surface `camera_view` prominently in the UI and tell the user to place the phone at floor level,
side-on, roughly 2 m away.

`cobra` additionally assumes the lower body sits in the **lower image region** (`FLOOR_Y=0.55`).
An unusual camera height will break it; that constant is the first thing to retune.

---

## 6. Building the Client

### Camera and MediaPipe

Match these settings — they are what the backend's thresholds were tuned against:

| Setting | Value |
| --- | --- |
| Model | `pose_landmarker_lite` (float16) |
| Model URL | `https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task` |
| WASM | `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.32/wasm` |
| Running mode | `VIDEO` |
| `numPoses` | `1` |
| Detection / presence / tracking confidence | `0.5` |
| Delegate | `GPU` (falls back to CPU) |
| Resolution | 1280×720 |

**Frame rate: throttle to 10–15 fps.** Yoga is static — 30 fps buys nothing and just burns
battery and bandwidth. The yoga route deliberately has **no server-side rate limiting** (unlike
the exercise route's `MAX_FRAMES_PER_SECOND`), so pacing is entirely your responsibility.

**Mirror the preview, not the landmarks.** Flip the video element with CSS
(`transform: scaleX(-1)`) so the user sees a mirror, but send the raw landmarks. The pose
modules use left/right symmetry (Tree picks the standing leg from ankle height, Warrior picks
the front leg from knee angle), so mirroring is harmless — but stay consistent so your skeleton
overlay lines up.

### Reference client

```ts
import { FilesetResolver, PoseLandmarker } from "@mediapipe/tasks-vision";

const BASE = "https://exercise-form-backend.onrender.com";
const WS_BASE = BASE.replace(/^http/, "ws");
const TARGET_FPS = 12;

// 1. Warm the free-tier dyno before the user hits "start" (30-60s cold start).
await fetch(`${BASE}/api/yoga/health`).catch(() => {});

// 2. Load the pose catalog — never hard-code labels.
const { poses } = await fetch(`${BASE}/api/yoga/poses`).then((r) => r.json());

// 3. MediaPipe.
const vision = await FilesetResolver.forVisionTasks(
  "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.32/wasm"
);
const landmarker = await PoseLandmarker.createFromOptions(vision, {
  baseOptions: {
    modelAssetPath:
      "https://storage.googleapis.com/mediapipe-models/pose_landmarker/" +
      "pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
    delegate: "GPU",
  },
  runningMode: "VIDEO",
  numPoses: 1,
  minPoseDetectionConfidence: 0.5,
  minPosePresenceConfidence: 0.5,
  minTrackingConfidence: 0.5,
});

// 4. Camera.
const stream = await navigator.mediaDevices.getUserMedia({
  video: { width: 1280, height: 720, facingMode: "user" },
});
const video = document.querySelector("video")!;
video.srcObject = stream;
await video.play();

// 5. WebSocket.
const clientId = crypto.randomUUID();           // matches ^[A-Za-z0-9_.:-]+$
const ws = new WebSocket(`${WS_BASE}/api/ws/yoga/${clientId}`);
ws.onmessage = (e) => render(JSON.parse(e.data));

let currentPose = "tree";                        // whatever the user picked
let lastSent = 0;

function loop() {
  requestAnimationFrame(loop);

  const now = performance.now();
  if (now - lastSent < 1000 / TARGET_FPS) return; // throttle
  if (ws.readyState !== WebSocket.OPEN) return;
  lastSent = now;

  const result = landmarker.detectForVideo(video, now);
  const landmarks = result.landmarks?.[0];
  if (!landmarks) return;                         // no body — skip the frame

  ws.send(
    JSON.stringify({
      landmarks: landmarks.map((l) => ({
        x: l.x,
        y: l.y,
        z: l.z,
        visibility: l.visibility ?? 1,
      })),
      pose: currentPose,                          // every frame, idempotent
      timestamp: now,
    })
  );
}
loop();

function render(r: YogaResponse) {
  ring.style.setProperty("--progress", String(r.hold_progress));
  caption.textContent = r.correction_message;
  drawSkeleton(r.joint_colors);                   // green / yellow / red per joint
  if (r.just_completed) chime();                  // fires exactly once per hold
}
```

### Response type

```ts
export interface YogaResponse {
  state: "idle" | "adjusting" | "holding";
  current_pose: string | null;
  pose_display: string;
  camera_view: "front" | "side";
  is_in_pose: boolean;
  hold_seconds: number;
  hold_target_seconds: number;
  hold_progress: number;      // 0..1
  hold_complete: boolean;
  just_completed: boolean;    // true on exactly one frame per hold
  violations: string[];
  corrections: string[];
  correction_message: string;
  joint_colors: Record<string, "green" | "yellow" | "red">;
  confidence: number;
  timestamp: number;
}

export interface YogaFrame {
  landmarks: { x: number; y: number; z: number; visibility: number }[];
  pose: string;
  timestamp?: number;
}
```

### Guided flows are your job, not the backend's

The backend is **stateless about sequencing**. To build a flow (Sun Salutation, a 5-minute
morning routine, etc.), keep the sequence entirely client-side:

1. Hold an array of `{ pose, holdSeconds?, cue }` steps and a `currentStep` index.
2. Send `pose: steps[currentStep].pose` with every frame.
3. On `just_completed`, advance `currentStep` — the next frame's new `pose` label automatically
   starts a fresh hold on the backend.
4. Optionally interleave a rest/transition step where you simply stop sending frames.

This keeps flows fully editable without a deploy, and lets you A/B sequences freely.

If you want a per-step hold that differs from the catalog default, run your own timer against
`hold_seconds` and ignore `hold_complete` — the backend's target is advisory.

### Voice cues

The browser **Web Speech API** (`speechSynthesis`) covers this with no dependency and no API
key. Two rules that matter in practice:

- **Debounce corrections.** `correction_message` can change every frame while the user wobbles.
  Only speak a message that has been stable for ~1 s and differs from the last thing spoken.
- **Never queue up.** Call `speechSynthesis.cancel()` before each utterance, or a 20-second hold
  produces a 40-second backlog of stale cues.

### Rendering `joint_colors`

Keys are snake_case joint names from `JointName` (`backend/exercises/base.py`). The MediaPipe
indices the yoga poses actually use:

| Index | Joint | Index | Joint |
| --- | --- | --- | --- |
| 11 | `left_shoulder` | 12 | `right_shoulder` |
| 13 | `left_elbow` | 14 | `right_elbow` |
| 15 | `left_wrist` | 16 | `right_wrist` |
| 23 | `left_hip` | 24 | `right_hip` |
| 25 | `left_knee` | 26 | `right_knee` |
| 27 | `left_ankle` | 28 | `right_ankle` |

A pose returns **green for every required joint by default**, then overwrites specific joints
with `yellow` (adjust this) or `red` (the primary fault). An empty `joint_colors` means the body
was not fully visible — draw the skeleton in a neutral colour rather than all-green.

---

## 7. Deployment

### CORS

Add your standalone app's origin to the backend's `CORS_ORIGINS` (comma-separated) in the Render
dashboard, or set `CORS_ORIGIN_REGEX` for preview deployments:

```env
CORS_ORIGINS=https://your-yoga-app.vercel.app,http://localhost:3000
CORS_ORIGIN_REGEX=https://your-yoga-app-.*\.vercel\.app
```

The defaults in `backend/config/settings.py` already cover `http://localhost:3000`,
`http://localhost:5173`, and the two existing Vercel apps.

> Browsers do **not** apply CORS preflight to WebSocket handshakes, so a missing origin will not
> break the socket — but it *will* break `GET /api/yoga/poses` and `/api/yoga/health`. Configure
> it properly rather than relying on that.

### Cold starts

The backend runs on Render's **free tier**. After ~15 minutes of inactivity the first request
takes **30–60 seconds** while the dyno spins up. For a yoga app that is the difference between
"broken" and "loading":

- `fetch('/api/yoga/health')` as soon as the session screen mounts — well before the user taps
  start — and show a warm-up state until it resolves.
- Give the WebSocket a generous connect timeout with retry/backoff.
- Because state is in-memory, a dyno restart mid-session drops the hold. Reconnect and re-send
  `pose`; the hold restarts from zero. Consider mirroring `hold_seconds` client-side if losing a
  25-second Warrior II hold would be unacceptable.

### Environment variables

Yoga mode only reads two settings of its own:

| Variable | Default | Notes |
| --- | --- | --- |
| `YOGA_HOLD_DEBOUNCE_FRAMES` | `10` | Frames of pose loss tolerated before a hold resets. Scale with your client frame rate. |
| `YOGA_DEFAULT_HOLD_SECONDS` | `20.0` | Fallback target for a pose that does not set its own. |

Plus the shared server settings (`HOST`, `PORT`, `DEBUG`, `CORS_ORIGINS`, `CORS_ORIGIN_REGEX`,
`MAX_CLIENT_ID_LENGTH`). Everything else in `settings.py` belongs to the exercise pipeline.

### Running only the yoga mode

The yoga router is mounted independently in `backend/main.py`:

```python
app.include_router(yoga_router, prefix="/api")
```

To ship a yoga-only deployment, drop the `api_router` and `upload_router` lines and the
`/uploads` static mount. The yoga pipeline imports only `config.settings`,
`exercises.base` (geometry helpers), `exercises.yoga_poses`, `exercises.yoga_registry`,
`pipeline.hold_timer`, and `state_machine.yoga_manager` — none of the HMM, Kalman,
feature-extraction, rep-counting, or upload modules. That also lets you cut `scipy` from
`requirements.txt`; `numpy`, `fastapi`, `uvicorn`, `pydantic`, and `pydantic-settings` are
enough.

---

## 8. Extending

### Adding a pose

1. Subclass `BaseYogaPose` in `backend/exercises/yoga_poses.py`. Set `name`, `display_name`,
   `sanskrit`, `camera_view`, `target_hold_seconds`; implement `required_joints` and
   `evaluate(lm)` returning a `YogaEvaluation`.
2. Register it in `YOGA_POSE_MODULES` in `backend/exercises/yoga_registry.py`. The catalog
   endpoint, `SUPPORTED_YOGA_LABELS`, and `YogaManager` all derive from that dict — nothing else
   needs touching.
3. Add a test in `backend/tests/test_yoga_poses.py` with a synthetic skeleton.

Convention: start from `self._green()`, append a `violation` + a matching `correction` for each
fault, and mark the offending joints `yellow` (adjust) or `red` (primary fault). `is_in_pose` is
`not violations`.

### Retuning

Every threshold is a class constant. Turn on `DETECTION_DEBUG_LOG=true`, record a session, and
adjust. Poses fail in two directions worth naming:

- **Too strict** → the user is visibly in the pose but `hold_seconds` never accumulates. Loosen
  the angle constants (e.g. `MIN_LEG_STRAIGHT`).
- **Too jittery** → the hold resets repeatedly. Raise `YOGA_HOLD_DEBOUNCE_FRAMES` first; only
  then loosen thresholds.

---

## 9. Testing

```powershell
cd "D:\work\FYP FINAL\form-checking-backend\backend"
pytest tests\test_yoga_poses.py tests\test_yoga_ws.py tests\test_hold_timer.py -q
```

Yoga coverage: per-pose detection against synthetic skeletons, `HoldTimer` debounce/latch
behaviour, `YogaManager` pose-switch hold reset, and the WebSocket + REST endpoints via
FastAPI's `TestClient`. Time-dependent tests monkeypatch `pipeline.hold_timer.time.time`, so
they are deterministic.

The full backend suite is `pytest` from the same directory.

---

## 10. Known Limitations

- **Floor poses are the weak link.** `downward_dog` and `cobra` need a side view at floor height
  and still detect less reliably than standing poses. Flag this in the UI.
- **No persistence.** Sessions live in memory, per WebSocket connection. Completed holds are not
  stored anywhere — persist them client-side if you want history.
- **No per-connection rate limiting** on the yoga endpoint. Throttle in the client.
- **Single body only** (`numPoses: 1`). Two people in frame produces undefined behaviour.
- **2D geometry.** Every check uses image-space `x`/`y`; MediaPipe's `z` is accepted but only
  `calculate_angle` uses it. Rotation away from the expected camera view degrades accuracy —
  hence the explicit `camera_view` field.
- **No authentication** on the WebSocket. Anyone with the URL can open a session.

---

## Related

- [README.md](../README.md) — full backend overview, exercise mode
- [backend/exercises/yoga_poses.py](../backend/exercises/yoga_poses.py) — the eight detectors
- [backend/pipeline/hold_timer.py](../backend/pipeline/hold_timer.py) — hold timing
- [backend/state_machine/yoga_manager.py](../backend/state_machine/yoga_manager.py) — session state
- [backend/api/yoga_routes.py](../backend/api/yoga_routes.py) — WebSocket + REST

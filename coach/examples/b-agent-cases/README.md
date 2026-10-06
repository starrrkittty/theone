# B Agent Input Cases

These cases use B's normalized movement JSON contract. They are synthetic
controlled examples for checking expert routing and measurement boundaries;
they are not real people, A-group model outputs, scientific labels, or
movement-quality ground truth. Angle and confidence values are fabricated
test inputs, not measured or validated performance data.

| File | Expected deterministic evidence result |
| --- | --- |
| `squat_target_met.json` | `within_project_target` |
| `squat_target_missed.json` | `outside_project_target` |
| `squat_insufficient_evidence.json` | `insufficient_evidence` because the view is frontal |
| `squat_low_confidence.json` | `insufficient_evidence` because landmark confidence is below the data gate |
| `plank_explicit_sag.json` | `within_project_target`; uses only the explicit `trunk_sag_angle` field |
| `semantic_lunge.json` | `non_numeric_guidance`; category recognition does not verify form |
| `hip_hinge_controlled.json` | Side-view hip/knee/trunk observations for the hinge specialist |
| `push_up_observed.json` | Side-view elbow observations for the push specialist |
| `band_row_front.json` | Front-view shoulder-elevation proxy for the pull specialist |
| `forward_lunge_side.json` | Side-view lunge observations with support side and phase |
| `alternate_bicep_curl.json` | Alternating-arm curl with the active arm identified |
| `single_leg_balance_front.json` | Frontal sway proxy; no trend or fall-risk inference |
| `jumping_jack_category.json` | Category-only cardio example with no joint findings |
| `yoga_tree_category.json` | Category-only yoga example with no joint findings |
| `plank_explicit_sag_contrast.json` | Plank contrast with a larger measured proxy angle |
| `semantic_lunge_uncertain.json` | Lower-confidence lunge-family classification, no pose correction |
| `hip_hinge_larger_trunk_angle.json` | Hinge contrast; angle change is not a danger label |
| `push_up_larger_elbow_range.json` | Push-up angle contrast against a provisional project proxy |
| `band_row_larger_shoulder_proxy.json` | Row shoulder-proxy contrast, not a universal threshold |
| `forward_lunge_front_proxy.json` | Front-view projected knee-path proxy |
| `alternate_bicep_curl_right_active.json` | Alternating curl with the right arm active |
| `single_leg_balance_larger_sway.json` | Balance proxy contrast without fall-risk inference |
| `jumping_jack_category_uncertain.json` | Lower-confidence cardio category, no joint-angle correction |
| `yoga_tree_unsupported.json` | Yoga category with support not reported |

The testbench includes a batch endpoint. `检查动作样例` processes all movement
cases through deterministic evidence review without a model. `批量调用动作
Agent` sends each case to the model separately and may incur one API call per
case. Results include a per-case success or error.

The numeric results refer only to the current provisional project targets. They
must not be interpreted as universal form, safety, or medical judgments.

## Run

From the `outputs/fitness_ab` directory, start the B demo server:

```powershell
.\.venv\Scripts\python.exe coach\serve_demo.py
```

In another PowerShell window, post a case to the deterministic evidence endpoint:

```powershell
$case = Get-Content .\coach\examples\b-agent-cases\squat_target_met.json -Raw
Invoke-RestMethod -Uri http://127.0.0.1:8765/api/movement/evidence `
  -Method Post -ContentType 'application/json' -Body $case |
  ConvertTo-Json -Depth 20
```

To request the AI movement report instead, post the same case to
`/api/movement/analyze`. This requires a model configured in the backend's
`coach/config.json` or the `FITNESS_API_KEY`, `FITNESS_BASE_URL`, and
`FITNESS_MODEL` environment variables. Do not put a real API key in these case
files or commit it.

The testbench also loads complete B task requests from `examples/`:
`training_plan_strength.json` covers schedule, equipment, recent adherence and
recovery context; `workout_report_personalized.json` covers multiple exercises,
targets, perceived effort and a cautious movement observation;
`nutrition_personalized.json` covers dietary preference, a peanut allergy,
preferred/disliked foods, budget and cafeteria/cooking access. The UI's shared
user ID field overrides each sample's `user_id` when populated.

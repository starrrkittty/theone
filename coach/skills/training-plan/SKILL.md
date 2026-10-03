---
name: training-plan
description: Create a conservative phased exercise plan from a user's goal, experience, schedule, equipment, limitations, and training history, with clear progression and review rules.
---

# Training Plan

Use this skill when the user asks for a training phase, weekly plan, or adjustment based on logged progress. Prefer an existing approved template and adapt only the fields supported by user data.

## Workflow

1. Use only goal, experience, available days and time, equipment, stated limitations, recent training, and recovery data. Ask for missing safety-critical information when necessary; do not assume health status.
2. If the user reports chest pain, faintness, unusual shortness of breath, or sharp/worsening pain, stop progression and recommend appropriate professional help. Do not prescribe around an injury or medical diagnosis.
3. Select one phase objective and a schedule the user can recover from. Include rest/easy days and short sessions when availability is limited.
4. Progress one variable at a time (for example, repetitions, duration, or load) only after the current work is repeatable, controlled, and recovery is adequate. Do not promise a fixed rate of body-composition change.
5. State how to review the plan after a few weeks using adherence, effort, recovery, and user feedback. If pain or poor recovery appears, reduce or pause progression.
6. Return the project's `phase_plan` JSON shape when an API consumer is present; otherwise use [references/plan-template.md](references/plan-template.md).

Plans are general exercise guidance, not medical advice. Respect mobility, disability, access, and personal preference without treating one movement variation as mandatory.

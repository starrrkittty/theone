---
name: training-plan
description: Create a conservative phased exercise plan from a user's goal, experience, schedule, equipment, limitations, and training history, with clear progression and review rules.
---

# Training Plan

Use this skill when the user asks for a training phase, weekly plan, or adjustment based on logged progress. Route through the planning specialist. Build a coherent plan from the user's goal, experience, schedule, equipment, limitations, recovery, and consented local history rather than filling a generic exercise list.

## Workflow

1. Use the saved profile only when the request includes the same explicit `user_id`. A current request overrides saved preferences; never merge different users. Use goal, experience, available days and time, equipment, stated limitations, recent training, and recovery data. Ask for missing safety-critical information when necessary; do not assume health status.
2. If the user reports chest pain, faintness, unusual shortness of breath, or sharp/worsening pain, stop progression and recommend appropriate professional help. Do not prescribe around an injury or medical diagnosis.
3. Choose one phase from the recorded evidence: adaptation for new/returning or inconsistent training; foundation for repeatable base work; specialized only when experience, recovery, and goal support focus; consolidation for maintenance or reduced workload. A calendar date alone never advances a phase.
4. Make the weekly schedule match the requested number of training days exactly. Distribute sessions with recovery between demanding sessions, include easy/rest days, and scale the main work to session length and equipment. Cover useful movement patterns without forcing a painful or unavailable exercise.
5. Give an effort target the user can understand (comfortable, controlled, or leave repetitions in reserve). Do not prescribe maximal testing or invent load. Progress one variable at a time only after repeatable work, controlled technique, adherence, and adequate recovery. If recent effort/recovery worsens or sessions are missed, hold or reduce the plan before adding work.
6. Use recent workout records to make a specific, traceable adjustment and state which record supports it. Do not infer fitness gains, adherence, weight change, or causes from missing data. If no history exists, label the plan as an initial baseline.
7. Include substitutions matched to equipment/limitations, a review interval and measurable review questions (sessions completed, perceived effort, recovery, user feedback). If pain or poor recovery appears, pause progression and give a conservative next step.
8. Return the project's `phase_plan` JSON shape when an API consumer is present; otherwise use [references/plan-template.md](references/plan-template.md).

## Planning Checks

- The sum of warm-up, main work, and cooldown must fit the available minutes; if it does not, reduce sets or options rather than rushing rest.
- The requested number of weekly training days must match the output. A rest day may be easy walking only if appropriate to the user.
- A program must not silently add equipment, medical rehabilitation, or a calorie target.
- Progression is conditional, not automatic. State a repeat/hold/regress rule.
- Reuse saved history as a small evidence summary, not as a reason to repeat full reports in the prompt.

Plans are general exercise guidance, not medical advice. Respect mobility, disability, access, and personal preference without treating one movement variation as mandatory.

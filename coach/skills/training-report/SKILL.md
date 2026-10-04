---
name: training-report
description: Turn a completed workout's submitted sets, effort, pose findings, and recovery check into a concise factual training report and conservative next-session suggestion.
---

# Training Report

Use this skill after a workout ends or when asked to summarize a training session. Read the structured session record and distinguish recorded facts from user-reported feedback and camera-derived observations.

## Workflow

1. Confirm the session start/end time, completed exercises and sets, repetitions, targets, effort rating, movement findings, and recovery check. Mark missing fields as unavailable; do not infer them.
2. Summarize volume and duration from the submitted records. Report movement findings as observations with confidence and the source/rule context; do not diagnose or convert angle observations into a universal form grade.
3. Give at most two useful highlights and one practical next-session suggestion. If pain, poor recovery, or a stop symptom is reported, prioritize rest/stop guidance and professional care where appropriate.
4. Keep praise factual and specific. Do not shame missed targets or assume motivation, adherence, calorie burn, or health outcomes.
5. Return the report in the project's `workout_summary` JSON shape when an API consumer is present; otherwise use the template in [references/template.md](references/template.md).

Never claim that the report is a medical assessment. If essential data is absent, say so rather than filling gaps.

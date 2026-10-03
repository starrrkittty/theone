# Other Completed-Set Tests

2026-10-03. These tests use engineered landmark sequences, not captured people.
They check classification, temporal accounting and evidence contracts. They do
not establish real-video recognition accuracy or scientific coaching quality.

| Fixture | Reference | Actual completed-set result |
| --- | --- | --- |
| Ordinary curl | 2 complete repetitions | bicep_curl, 2 |
| Alternating curl | 1 complete left/right pair | alternate_bicep_curl, 1 |
| Push-up | 2 complete repetitions | pushup, 2 |
| Forearm plank | 179/30 seconds, zero repetitions | plank, 5.9667 seconds, zero repetitions |
| Static standing | unknown | unknown |
| Static bent arms | unknown | unknown |
| Static push-up bottom | unknown moving action | unknown |

Alternating curls count complete observed pairs. The fixture starts with one arm
bent, so its initial unobserved half-cycle cannot count as a complete repetition.
The plank duration comes from observation timestamps, not CPU processing duration.
The webpage now displays plank duration in seconds rather than a misleading rep
count alone.

All four positive fixtures produce an eligible representative A evidence snapshot;
that is permission to request review, not a statement that form is correct.
No real model calls were made. Existing explicit mock tests check A/B Skill routing.

Artifacts:

- `tools/make_synthetic_cases.py`: reusable fixtures for ten diagnostic sequences.
- `evaluation/synthetic_cases.json`: generated landmark sequences.
- `evaluation/synthetic_completed_sets.json`: full per-clip diagnostic results.
- `backend/tests/test_other_completed_sets.py`: exact counts, static abstention,
  plank time and compact evidence regressions.

Reproduce from this directory:

```powershell
python tools/make_synthetic_cases.py
python tools/evaluate_completed_sets.py evaluation/synthetic_cases.json --output evaluation/synthetic_completed_sets.json
```

174 backend tests, 15 frontend tests and production build passed. Real positive
video validation for push-up/plank/curl/alternate curl is still missing. The earlier
public UI-PRMD subset contains only one supported positive class, squat. Independent
RGB clips and trustworthy phase/count labels are needed before claiming accuracy.

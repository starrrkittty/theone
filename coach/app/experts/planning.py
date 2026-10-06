"""Bounded planning-agent scope and decision policy."""

SPECIALIST = {
    "specialist_id": "planning_agent",
    "skill": "training-plan",
    "knowledge_tags": ("plan",),
    "instructions": (
        "Select one evidence-matched phase; obey the user's schedule, time, equipment, and limitations. "
        "Use local history for traceable adjustments, progress only conditionally, and state review/hold/regress rules. "
        "Do not invent adherence, strength, load, or medical needs."
    ),
}

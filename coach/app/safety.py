from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas import MovementInput

STOP_SYMPTOMS = {"sharp_pain", "chest_pain", "dizziness", "breathing_difficulty", "faintness"}


def safety_messages(movement: "MovementInput") -> list[str]:
    reported = {item.strip().lower() for item in movement.reported_symptoms}
    matched = sorted(reported & STOP_SYMPTOMS)
    if matched:
        return ["Stop the exercise now. Seek appropriate medical help for severe, persistent, or concerning symptoms."]
    return []

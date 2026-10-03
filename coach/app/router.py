from app.experts.movement import BY_EXERCISE, SPECIALISTS, catalog


class AgentRouter:
    def __init__(self) -> None:
        self.specialists = SPECIALISTS

    def route(self, exercise_id: str):
        agent = BY_EXERCISE.get(exercise_id)
        return [agent] if agent else []

    def catalog(self) -> list[dict[str, object]]:
        return catalog()


agent_router = AgentRouter()

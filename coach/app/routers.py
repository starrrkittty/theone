from fastapi import APIRouter, HTTPException
from app.agents import service
from app.engine import InputError, experts_catalog
from app.chat import respond as chat_respond
from app.model_client import ConfigurationError, ModelError
from app.workflow import run_workflow
from app.group_adapters import from_group_a
from app.history import delete, memory_overview, recent, save_profile
from app.engine import validate_movement
from app.movement_evidence import measurement_review
from app.routing import resolve_movement, resolve_task

router = APIRouter()


def run(task, payload):
    try:
        return service.run(task, payload)
    except ConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    except ModelError as exc:
        raise HTTPException(502, str(exc)) from exc
    except (InputError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/status")
def status():
    try:
        return service.client.status()
    except ConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/experts")
def experts():
    return experts_catalog()


@router.post("/movement/analyze")
def movement(payload: dict):
    return run("movement", from_group_a(payload))


@router.post("/movement/route")
def movement_route(payload: dict):
    try:
        _, route = resolve_movement(payload)
        return {"route": route}
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/plans/route")
def plan_route(payload: dict):
    try:
        _, route = resolve_task("plan", payload)
        return {"route": route}
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/nutrition/route")
def nutrition_route(payload: dict):
    try:
        _, route = resolve_task("nutrition", payload)
        return {"route": route}
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/workouts/route")
def report_route(payload: dict):
    try:
        _, route = resolve_task("report", payload)
        return {"route": route}
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/movement/evidence")
def evidence(payload: dict):
    try:
        payload = from_group_a(payload)
        validate_movement(payload)
        return {"measurement_review":measurement_review(payload), "agent":{"mode":"measurement_tool", "model_called":False}}
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/plans/phase")
def plan(payload: dict):
    return run("plan", payload)


@router.post("/nutrition/advice")
def nutrition(payload: dict):
    return run("nutrition", payload)


@router.post("/workouts/summary")
def report(payload: dict):
    return run("report", payload)


@router.post("/workouts/{session_id}/summary")
def session_report(session_id: str, payload: dict):
    return run("report", {**payload, "session_id": session_id})


@router.get("/history")
def reports(user_id: str):
    try:
        return {"reports": recent(user_id)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/memory")
def memory(user_id: str):
    try:
        return memory_overview(user_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/memory/profile")
def profile(payload: dict):
    try:
        return {"profile": save_profile(payload.get("user_id"), payload.get("profile"))}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/memory/delete")
def delete_memory(payload: dict):
    try:
        delete(payload.get("user_id"))
        return {"deleted": True}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/chat")
def chat(payload: dict):
    try:
        return chat_respond(payload, service.client)
    except ConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    except ModelError as exc:
        raise HTTPException(502, str(exc)) from exc
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/history/delete")
def delete_reports(payload: dict):
    try:
        delete(payload.get("user_id"))
        return {"deleted": True}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/workflow")
def workflow(payload: dict):
    try:
        return run_workflow(payload)
    except ConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    except ModelError as exc:
        raise HTTPException(502, str(exc)) from exc
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc

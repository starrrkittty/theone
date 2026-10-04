from fastapi import APIRouter, HTTPException
from app.agents import service
from app.engine import InputError, experts_catalog
from app.model_client import ConfigurationError, ModelError
from app.workflow import run_workflow
from app.group_adapters import from_group_a
from app.history import recent, delete
from app.engine import validate_movement
from app.movement_evidence import measurement_review

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

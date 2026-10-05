"""Small product contract for the Android Training Bridge v1 consumer."""
from contextlib import closing
from datetime import date, datetime
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import sqlite3
import time
from uuid import uuid4
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.agents import service
from app.agent_tools import load_skill, retrieve_knowledge
from app.model_client import ConfigurationError, ModelError


def fail(status, code, message, retryable=False):
    raise HTTPException(status, {"code": code, "message": message, "retryable": retryable})


class MobileRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def wrapped(request):
            try:
                return await handler(request)
            except RequestValidationError:
                fail(422, "INVALID_REQUEST", "请求不符合 APP v1 契约；请检查字段、枚举和桥返回值。")
        return wrapped


def authorize(request: Request):
    token = os.environ.get("FITNESS_APP_DEV_TOKEN", "")
    if token:
        if not hmac.compare_digest(request.headers.get("authorization", "").encode(), ("Bearer " + token).encode()):
            fail(401, "UNAUTHORIZED", "开发访问凭据无效。")
    elif not request.client or request.client.host not in {"127.0.0.1", "::1"}:
        fail(503, "APP_ACCESS_NOT_CONFIGURED", "远程 APP 联调需配置服务端开发访问凭据。")


router = APIRouter(prefix="/app/v1", tags=["APP v1"], route_class=MobileRoute,
                   dependencies=[Depends(authorize)])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Profile(StrictModel):
    schema_version: Literal[1]
    goal: Literal["建立运动习惯", "提升力量", "改善体能"]
    experience: Literal["新手", "有规律运动"]
    days_per_week: int = Field(ge=1, le=4)
    minutes_per_session: Literal[10, 15, 20, 30]
    has_equipment: bool
    diet_preference: Literal["无特别偏好", "素食", "有过敏或特殊限制"]

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("schema_version must be an integer")
        return value


class Exercise(StrictModel):
    exercise_id: Literal["squat", "push_up"]
    completed_sets: int = Field(ge=0, le=1)
    completed_reps: int = Field(ge=0, le=10000)
    quality_trend: None = None
    main_error_code: None = None


class Session(StrictModel):
    schema_version: Literal[1]
    session_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    status: Literal["completed", "cancelled", "interrupted"]
    finished_at: str = Field(min_length=1, max_length=64)
    duration_seconds: int = Field(ge=0, le=86400)
    exercises: list[Exercise] = Field(max_length=1)
    agent_summary: None = None
    next_plan_changed: Literal[False] = False
    source: Literal["real"]

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("schema_version must be an integer")
        return value

    @field_validator("finished_at")
    @classmethod
    def zoned_time(cls, value):
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("finished_at requires a timezone")
        return value

    @model_validator(mode="after")
    def completed_has_exercise(self):
        if self.status == "completed" and len(self.exercises) != 1:
            raise ValueError("completed session requires one exercise")
        return self


class PlanRequest(StrictModel):
    profile: Profile
    history: list[Session] = Field(default_factory=list, max_length=30)
    executable_exercises: list[Literal["squat", "push_up"]] = Field(default_factory=lambda: ["squat"], min_length=1, max_length=2)
    local_date: str | None = Field(default=None, max_length=10)

    @field_validator("local_date")
    @classmethod
    def calendar_date(cls, value):
        if value is not None and (len(value) != 10 or date.fromisoformat(value).isoformat() != value):
            raise ValueError("local_date must be YYYY-MM-DD")
        return value


class NutritionRequest(StrictModel):
    profile: Profile


class ProgressRequest(StrictModel):
    profile: Profile
    history: list[Session] = Field(default_factory=list, max_length=30)
    local_date: str = Field(min_length=10, max_length=10)

    @field_validator("local_date")
    @classmethod
    def calendar_date(cls, value):
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("local_date must be YYYY-MM-DD")
        return value


class SummaryRequest(StrictModel):
    installation_id: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    profile: Profile
    session: Session
    history: list[Session] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def unique_history(self):
        ids = [row.session_id for row in self.history]
        if len(set(ids)) != len(ids) or self.session.session_id in ids:
            raise ValueError("history must exclude the current session and duplicates")
        return self


class PlanItem(StrictModel):
    exercise_id: Literal["squat", "push_up"]
    title: str = Field(min_length=1, max_length=80)
    target_sets: Literal[1]
    target_reps: int = Field(ge=1, le=8)
    rest_seconds: Literal[45]


class PlanText(StrictModel):
    stage_name: str = Field(min_length=1, max_length=80)
    headline: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=600)
    item: PlanItem | None


class NutritionText(StrictModel):
    title: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1, max_length=1200)


class NutritionChoice(StrictModel):
    focus: Literal["regular_meals", "training_day", "hydration"]


class SummaryText(StrictModel):
    highlights: list[Literal["counts_are_device_estimates", "recovery_not_recorded"]] = Field(max_length=2)
    next_session_suggestion: Literal["repeat_without_progression", "review_capture_setup", "seek_personal_guidance"]


class ProgressChoice(StrictModel):
    next_step: Literal["maintain_schedule", "review_schedule", "resume_when_ready"]


class PlanItemResponse(PlanItem):
    id: str


class PlanResponse(PlanText):
    plan_id: str
    item: PlanItemResponse | None
    source: Literal["agent", "template"]


class NutritionResponse(NutritionText):
    source: Literal["agent", "template"]


class SummaryFacts(StrictModel):
    status: Literal["completed", "cancelled", "interrupted"]
    duration_seconds: int
    sets: int
    reps: int
    exercises: list[Literal["squat", "push_up"]]
    quality_available: Literal[False]
    error_evidence_available: Literal[False]


class SummaryResponse(StrictModel):
    session_id: str
    agent_summary: str
    quality_trend: None
    main_error_code: None
    next_plan_changed: Literal[False]
    updated_plan: None
    source: Literal["agent"]
    facts: SummaryFacts
    limitations: list[str]


class ProgressResponse(StrictModel):
    week_start: str
    week_end: str
    completed_training_days: int
    weekly_day_goal: int
    completed_sessions: int
    total_duration_seconds: int
    total_reps: int
    reps_by_exercise: dict[str, int]
    cancelled_sessions: int
    interrupted_sessions: int
    status: Literal["no_completed_sessions", "below_goal", "goal_reached"]
    summary: str
    next_step: str
    quality_available: Literal[False]
    source: Literal["agent", "template"]


def generate(task, data, output_type):
    specialist = {"plan": "planning_agent", "nutrition": "nutrition_agent", "report": "report_agent", "progress": "report_agent"}[task]
    knowledge = retrieve_knowledge("report" if task == "progress" else task, specialist, json.dumps(data, ensure_ascii=False))
    instructions = load_skill("app-coach-v1")
    system = (instructions + "\n只返回符合以下 JSON Schema 的对象，不返回额外字段：\n"
              + json.dumps(output_type.model_json_schema(), ensure_ascii=False))
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": json.dumps({"task": task, "facts": data, "knowledge": knowledge}, ensure_ascii=False)}]
    try:
        for attempt in range(2):
            content, _ = service.client.complete(messages)
            try:
                output = output_type.model_validate_json(content)
                if task == "plan" and output.item:
                    if output.item.exercise_id not in data["executable_exercises"]:
                        raise ValueError("exercise not executable")
                    ceiling = 6 if data["profile"]["experience"] == "新手" else 8
                    if output.item.target_reps > ceiling:
                        raise ValueError("repetition cap exceeded")
                if task == "report":
                    status = data["session"]["status"]
                    suggestion = output.next_session_suggestion
                    if (status == "completed" and suggestion == "review_capture_setup") or (status != "completed" and suggestion == "repeat_without_progression"):
                        raise ValueError("suggestion conflicts with session status")
                if task == "progress" and data["status"] == "goal_reached" and output.next_step != "maintain_schedule":
                    raise ValueError("next step conflicts with completed day goal")
                if task == "progress" and data["status"] == "no_completed_sessions" and output.next_step != "resume_when_ready":
                    raise ValueError("next step conflicts with no completed sessions")
                return output.model_dump()
            except (ValidationError, ValueError):
                if attempt:
                    fail(502, "INVALID_MODEL_OUTPUT", "模型输出未通过 APP 契约校验。", True)
                messages += [{"role": "assistant", "content": content},
                             {"role": "user", "content": "输出未通过结构或可执行动作/次数上限检查，请按原始事实和契约修复。"}]
    except ConfigurationError:
        fail(503, "MODEL_NOT_CONFIGURED", "模型未配置，请使用 APP 本地模板。")
    except ModelError:
        fail(502, "MODEL_UNAVAILABLE", "模型繁忙、超时或供应商响应异常。", True)


@router.get("/capabilities")
def capabilities():
    return {"contract": "app_coach_v1", "schema_version": 1,
            "default_executable_exercises": ["squat"], "bridge_exercises": ["squat", "push_up"],
            "max_sets": 1, "pose_quality_evaluation": False, "persistent_plan_updates": False,
            "weekly_completion_gate": True,
            "health_profile_upload": False, "summary_idempotency": "installation_id + session_id",
            "authentication": "development_only; shared token is not user authentication"}


def plan_history_summary(request: PlanRequest):
    today = date.fromisoformat(request.local_date) if request.local_date else datetime.now().astimezone().date()
    week_start = today.toordinal() - today.weekday()
    weekly_days = set()
    exercise_counts = {exercise: 0 for exercise in request.executable_exercises}
    completed_sessions = 0
    for session in request.history:
        if session.status != "completed":
            continue
        finished = datetime.fromisoformat(session.finished_at.replace("Z", "+00:00")).date()
        if finished > today:
            continue
        completed_sessions += 1
        if week_start <= finished.toordinal() <= today.toordinal():
            weekly_days.add(finished.isoformat())
        for exercise in session.exercises:
            if exercise.exercise_id in exercise_counts:
                exercise_counts[exercise.exercise_id] += 1
    return {"local_date": today.isoformat(), "completed_training_days_this_week": len(weekly_days),
            "completed_today": today.isoformat() in weekly_days,
            "weekly_day_goal": request.profile.days_per_week,
            "completed_sessions_in_supplied_history": completed_sessions,
            "completed_sessions_by_exercise": exercise_counts,
            "quality_and_recovery_known": False}


@router.post("/plan", response_model=PlanResponse)
def plan(request: PlanRequest):
    history_summary = plan_history_summary(request)
    plan_id = "app_plan_" + uuid4().hex
    if history_summary["completed_today"] or history_summary["completed_training_days_this_week"] >= request.profile.days_per_week:
        reason = ("今天已记录一次完成训练，可安排休息或轻松活动。" if history_summary["completed_today"] else
                  f"本周已记录 {history_summary['completed_training_days_this_week']} 个训练日，达到设置的每周 {request.profile.days_per_week} 天目标；可安排休息或轻松活动。")
        return {"plan_id": plan_id, "stage_name": "本周安排", "headline": "今天安排休息",
                "reason": reason + "次数记录不能说明动作质量或恢复情况。",
                "item": None, "source": "template"}
    data = {"profile": request.profile.model_dump(),
            "executable_exercises": request.executable_exercises,
            "history_summary": history_summary}
    # Diet preference is irrelevant to exercise planning and stays out of its prompt.
    data["profile"].pop("diet_preference")
    result = generate("plan", data, PlanText)
    if history_summary["completed_sessions_in_supplied_history"]:
        result["reason"] = (f"本周已记录 {history_summary['completed_training_days_this_week']}/{request.profile.days_per_week} 个训练日。"
                            + result["reason"])
    result["reason"] = (result["reason"][:540] + " 尚无动作质量和恢复信息，本次不依据完成次数自动加量。")[:600]
    if result["item"]:
        result["item"]["id"] = plan_id + "_item_1"
        result["item"]["title"] = {"squat": "徒手深蹲", "push_up": "俯卧撑"}[result["item"]["exercise_id"]]
    return {"plan_id": plan_id, **result, "source": "agent"}


@router.post("/nutrition", response_model=NutritionResponse)
def nutrition(request: NutritionRequest):
    data = {"goal": request.profile.goal, "diet_preference": request.profile.diet_preference}
    if data["diet_preference"] == "有过敏或特殊限制":
        return {"title": "饮食限制需要进一步确认",
                "body": "尚未提供具体过敏或饮食限制，无法给出个体化餐食建议。请依照已明确的专业建议选择食物；这里不计算热量，也不判断具体食物是否安全。",
                "source": "template"}
    focus = generate("nutrition", data, NutritionChoice)["focus"]
    vegetarian = data["diet_preference"] == "素食"
    examples = ("豆类、豆制品及其他符合个人饮食习惯的食物" if vegetarian else
                "豆类、蛋、奶、鱼或肉等符合个人饮食习惯的食物")
    advice = {
        "regular_meals": ("日常饮食安排", f"尽量规律进餐，搭配蔬菜、水果、主食和{examples}，按食欲与实际活动安排份量。"),
        "training_day": ("训练日饮食安排", f"训练前后按饥饿感和日常作息正常进餐；可搭配主食、蔬菜及{examples}。无需为了这次训练强制加餐。"),
        "hydration": ("日常补水提醒", "日常留意口渴和活动环境，按需要饮水；不依据训练次数指定统一饮水量。进餐仍注意食物多样。"),
    }
    title, body = advice[focus]
    return {"title": title, "body": body, "source": "agent"}


@router.post("/progress/weekly", response_model=ProgressResponse)
def weekly_progress(request: ProgressRequest):
    today = date.fromisoformat(request.local_date)
    start_ordinal = today.toordinal() - today.weekday()
    week_start = date.fromordinal(start_ordinal)
    week_end = date.fromordinal(start_ordinal + 6)
    completed_days = set()
    completed_sessions = cancelled = interrupted = seconds = reps = 0
    by_exercise = {"squat": 0, "push_up": 0}
    for session in request.history:
        finished = datetime.fromisoformat(session.finished_at.replace("Z", "+00:00")).date()
        if not start_ordinal <= finished.toordinal() <= today.toordinal():
            continue
        if session.status == "cancelled":
            cancelled += 1
        elif session.status == "interrupted":
            interrupted += 1
        else:
            completed_days.add(finished.isoformat())
            completed_sessions += 1
            seconds += session.duration_seconds
            for exercise in session.exercises:
                by_exercise[exercise.exercise_id] += exercise.completed_reps
                reps += exercise.completed_reps
    status = ("no_completed_sessions" if not completed_sessions else
              "goal_reached" if len(completed_days) >= request.profile.days_per_week else "below_goal")
    steps = {"maintain_schedule": "按当前可用时间保持规律；不要仅凭次数增加训练量。",
             "review_schedule": "可检查接下来可用的训练日，选择适合自己的节奏。",
             "resume_when_ready": "需要时从少量练习重新开始；有不适时先暂停。"}
    default_choice = "maintain_schedule" if status == "goal_reached" else "resume_when_ready" if status == "no_completed_sessions" else "review_schedule"
    source = "template"
    choice = default_choice
    facts = {"status": status, "completed_training_days": len(completed_days),
             "weekly_day_goal": request.profile.days_per_week, "cancelled_sessions": cancelled,
             "interrupted_sessions": interrupted, "goal": request.profile.goal,
             "quality_available": False, "recovery_available": False}
    try:
        choice = generate("progress", facts, ProgressChoice)["next_step"]
        source = "agent"
    except HTTPException as exc:
        if exc.status_code not in {502, 503}:
            raise
    summary = (f"本周记录 {len(completed_days)}/{request.profile.days_per_week} 个已完成训练日，"
               f"{completed_sessions} 次完成训练，累计有效训练时长 {seconds} 秒、端侧记录 {reps} 次动作。"
               "取消和中断不计入完成；缺少动作质量与恢复数据，不能据此判断姿势进步。")
    return {"week_start": week_start.isoformat(), "week_end": week_end.isoformat(),
            "completed_training_days": len(completed_days), "weekly_day_goal": request.profile.days_per_week,
            "completed_sessions": completed_sessions, "total_duration_seconds": seconds,
            "total_reps": reps, "reps_by_exercise": by_exercise,
            "cancelled_sessions": cancelled, "interrupted_sessions": interrupted,
            "status": status, "summary": summary, "next_step": steps[choice],
            "quality_available": False, "source": source}


DATABASE = Path(__file__).resolve().parents[1] / "data" / "app_results.sqlite3"


def connect():
    DATABASE.parent.mkdir(exist_ok=True)
    connection = sqlite3.connect(DATABASE, timeout=3)
    connection.execute("CREATE TABLE IF NOT EXISTS results (scope TEXT, session TEXT, fingerprint TEXT, created REAL, response TEXT, PRIMARY KEY(scope, session))")
    return connection


def summarize(request):
    raw = request.session.model_dump()
    facts = {"status": raw["status"], "duration_seconds": raw["duration_seconds"],
             "sets": sum(e["completed_sets"] for e in raw["exercises"]),
             "reps": sum(e["completed_reps"] for e in raw["exercises"]),
             "exercises": [e["exercise_id"] for e in raw["exercises"]],
             "quality_available": False, "error_evidence_available": False}
    profile = request.profile.model_dump(exclude={"diet_preference"})
    narrative = generate("report", {"profile": profile, "session": facts,
                                    "history": [s.model_dump() for s in request.history]}, SummaryText)
    state = {"completed": "用户已结束本次训练", "cancelled": "本次训练已取消，不计入完成统计",
             "interrupted": "本次训练异常中断，不计入完成统计"}[raw["status"]]
    choices = {"counts_are_device_estimates": "次数来自端侧算法记录，未经过独立人工核验。",
               "recovery_not_recorded": "未记录自觉强度和恢复情况，不能据此安排进阶。",
               "repeat_without_progression": "下次先保持少量练习，不依据本次计数自动增加训练量；有不适时暂停。",
               "review_capture_setup": "继续训练前先确认相机、权限和全身入镜；存在不适时暂停。",
               "seek_personal_guidance": "需要个体化调整时，请结合实际感受和专业指导确认安排。"}
    summary = (f"{state}。端侧记录有效训练时长 {facts['duration_seconds']} 秒，"
               f"记录组数 {facts['sets']}，次数 {facts['reps']}。"
               "未提供动作质量证据，无法评价姿势或质量趋势。\n"
               + "\n".join(choices[key] for key in dict.fromkeys(narrative["highlights"] + [narrative["next_session_suggestion"]])))
    return {"session_id": raw["session_id"], "agent_summary": summary,
            "quality_trend": None, "main_error_code": None, "next_plan_changed": False,
            "updated_plan": None, "source": "agent",
            "facts": facts, "limitations": ["总结使用 APP 端侧记录，未经视频复核。", "生成式建议不等于测量事实。", "本接口没有保存或调整训练计划。"]}


@router.post("/sessions/summary", response_model=SummaryResponse)
def summary(request: SummaryRequest):
    scope = sha256(request.installation_id.encode()).hexdigest()
    session = request.session.session_id
    # Only the session determines identity; later history/profile changes do not regenerate it.
    fingerprint = sha256(json.dumps(request.session.model_dump(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    owner = False
    lease = time.time()
    try:
        with closing(connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM results WHERE created < ?", (time.time() - 30 * 86400,))
            row = connection.execute("SELECT fingerprint, created, response FROM results WHERE scope=? AND session=?", (scope, session)).fetchone()
            if row:
                if row[0] != fingerprint:
                    fail(409, "SESSION_CONFLICT", "同一 session_id 的训练事实发生变化。")
                if row[2] is not None:
                    return json.loads(row[2])
                # A crashed worker's lease may be reclaimed after ten minutes.
                if time.time() - row[1] < 600:
                    fail(409, "REQUEST_IN_PROGRESS", "本次总结正在生成，请稍后重试。", True)
                connection.execute("DELETE FROM results WHERE scope=? AND session=?", (scope, session))
            connection.execute("INSERT INTO results VALUES(?,?,?,?,NULL)", (scope, session, fingerprint, lease))
            owner = True
        result = summarize(request)
        with closing(connect()) as connection, connection:
            updated = connection.execute("UPDATE results SET response=? WHERE scope=? AND session=? AND created=? AND response IS NULL", (json.dumps(result, ensure_ascii=False), scope, session, lease))
            if updated.rowcount != 1:
                fail(409, "REQUEST_SUPERSEDED", "本次生成已被删除或其他处理取代，请检查当前训练记录。")
        return result
    except sqlite3.Error:
        fail(503, "STORAGE_UNAVAILABLE", "总结存储暂不可用。", True)
    finally:
        if owner:
            try:
                with closing(connect()) as connection, connection:
                    connection.execute("DELETE FROM results WHERE scope=? AND session=? AND created=? AND response IS NULL", (scope, session, lease))
            except sqlite3.Error:
                pass  # Failed leases can be reclaimed after ten minutes.


class DeleteRequest(StrictModel):
    installation_id: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


@router.post("/data/delete")
def delete_data(request: DeleteRequest):
    scope = sha256(request.installation_id.encode()).hexdigest()
    try:
        with closing(connect()) as connection, connection:
            connection.execute("DELETE FROM results WHERE scope=?", (scope,))
    except sqlite3.Error:
        fail(503, "STORAGE_UNAVAILABLE", "删除暂不可用。", True)
    return {"deleted": True}

"""User-scoped local memory for plans, nutrition, training, and coach chat."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


DATABASE = Path(__file__).resolve().parents[1] / "data" / "history.sqlite3"
LIST_FIELDS = {
    "equipment", "limitations", "dietary_preferences", "allergies",
    "medical_conditions", "preferred_foods", "disliked_foods",
}
PROFILE_FIELDS = {
    "goal", "experience", "days_per_week", "minutes_per_session",
    "equipment", "limitations", "dietary_preferences", "allergies",
    "medical_conditions", "preferred_foods", "disliked_foods", "budget",
    "cooking_access", "preferred_language",
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def validate_user_id(user_id):
    if not isinstance(user_id, str) or not user_id.strip() or len(user_id.strip()) > 80:
        raise ValueError("user_id 必须是 1 到 80 个字符的非空字符串。")
    if any(ord(char) < 32 for char in user_id):
        raise ValueError("user_id 不能包含控制字符。")
    return user_id.strip()


def connect():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE, timeout=10)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE IF NOT EXISTS reports (user_id TEXT, session_id TEXT, recorded_at TEXT, payload TEXT, PRIMARY KEY(user_id, session_id))")
    connection.execute("CREATE TABLE IF NOT EXISTS profiles (user_id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, payload TEXT NOT NULL)")
    connection.execute("CREATE TABLE IF NOT EXISTS memory_entries (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
    connection.execute("CREATE INDEX IF NOT EXISTS memory_entries_user_time ON memory_entries(user_id, created_at DESC)")
    connection.execute("CREATE TABLE IF NOT EXISTS chat_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, created_at TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL)")
    connection.execute("CREATE INDEX IF NOT EXISTS chat_messages_user_time ON chat_messages(user_id, id DESC)")
    return connection


def recent(user_id):
    user_id = validate_user_id(user_id)
    with closing(connect()) as connection:
        rows = connection.execute("SELECT payload FROM reports WHERE user_id=? ORDER BY recorded_at DESC LIMIT 20", (user_id,)).fetchall()
    return [json.loads(row[0]) for row in rows]


def get_profile(user_id):
    user_id = validate_user_id(user_id)
    with closing(connect()) as connection:
        row = connection.execute("SELECT payload FROM profiles WHERE user_id=?", (user_id,)).fetchone()
    return json.loads(row[0]) if row else {}


def save_profile(user_id, profile):
    user_id = validate_user_id(user_id)
    if not isinstance(profile, dict):
        raise ValueError("profile 必须是 JSON 对象。")
    unknown = set(profile) - PROFILE_FIELDS
    if unknown:
        raise ValueError("profile 包含不支持字段：" + ", ".join(sorted(unknown)))
    normalized = {}
    if "goal" in profile:
        if profile["goal"] not in {"general_fitness", "strength", "fat_loss", "mobility", "endurance"}:
            raise ValueError("goal 无效。")
        normalized["goal"] = profile["goal"]
    if "experience" in profile:
        if profile["experience"] not in {"beginner", "intermediate", "advanced"}:
            raise ValueError("experience 无效。")
        normalized["experience"] = profile["experience"]
    for key, lower, upper in (("days_per_week", 1, 7), ("minutes_per_session", 10, 180)):
        if key in profile:
            value = profile[key]
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f"{key} 必须在 {lower} 到 {upper} 之间。")
            normalized[key] = value
    for key in LIST_FIELDS:
        if key in profile:
            value = profile[key]
            if not isinstance(value, list) or len(value) > 30 or any(not isinstance(item, str) or len(item) > 120 for item in value):
                raise ValueError(f"{key} 必须是最多 30 项的字符串数组。")
            normalized[key] = list(dict.fromkeys(item.strip() for item in value if item.strip()))
    for key in ("budget", "cooking_access", "preferred_language"):
        if key in profile:
            value = profile[key]
            if not isinstance(value, str) or len(value) > 160:
                raise ValueError(f"{key} 必须是 160 个字符以内的字符串。")
            normalized[key] = value.strip()
    with closing(connect()) as connection, connection:
        connection.execute(
            "INSERT INTO profiles VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET updated_at=excluded.updated_at,payload=excluded.payload",
            (user_id, _now(), json.dumps(normalized, ensure_ascii=False)),
        )
    return normalized


def save(user_id, report):
    user_id = validate_user_id(user_id)
    if not isinstance(report, dict) or not isinstance(report.get("session_id"), str):
        raise ValueError("训练汇报缺少 session_id。")
    stamp = _now()
    compact_report = {key: report.get(key) for key in (
        "session_id", "duration_minutes", "completed_exercises", "sets_completed", "reps_completed",
        "average_perceived_effort", "incomplete_targets", "movement_highlights", "caution_observations",
        "recovery_check", "reported_stop_symptom", "user_feedback", "next_session_suggestion",
    ) if key in report}
    encoded = json.dumps(compact_report, ensure_ascii=False)
    with closing(connect()) as connection, connection:
        connection.execute(
            "INSERT INTO reports VALUES(?,?,?,?) ON CONFLICT(user_id,session_id) DO UPDATE SET recorded_at=excluded.recorded_at,payload=excluded.payload",
            (user_id, report["session_id"], stamp, encoded),
        )
    record_memory(user_id, "workout", {"request": {}, "result": report}, report["session_id"])


def record_memory(user_id, kind, value, key=None):
    user_id = validate_user_id(user_id)
    if kind not in {"workout", "plan", "nutrition"} or not isinstance(value, dict):
        raise ValueError("本地记忆类型或内容无效。")
    request = value.get("request", {})
    result = value.get("result", {})
    if kind == "workout":
        compact = {
            "session_id": result.get("session_id"),
            "duration_minutes": result.get("duration_minutes"),
            "completed_exercises": result.get("completed_exercises", []),
            "sets_completed": result.get("sets_completed"),
            "reps_completed": result.get("reps_completed"),
            "average_perceived_effort": result.get("average_perceived_effort"),
            "recovery_check": result.get("recovery_check"),
            "reported_stop_symptom": result.get("reported_stop_symptom", False),
            "user_feedback": result.get("user_feedback", []),
        }
    elif kind == "plan":
        compact = {
            "goal": request.get("goal", result.get("goal")),
            "experience": request.get("experience"),
            "weekly_sessions": result.get("weekly_sessions", request.get("days_per_week")),
            "minutes_per_session": result.get("minutes_per_session", request.get("minutes_per_session")),
            "phase": result.get("phase"),
            "duration_weeks": result.get("duration_weeks"),
            "progression_rule": result.get("progression_rule"),
        }
    else:
        compact = {
            "goal": request.get("goal"),
            "dietary_preferences": request.get("dietary_preferences", []),
            "allergies": request.get("allergies", []),
            "medical_conditions": request.get("medical_conditions", []),
            "suggestions": result.get("suggestions", []),
            "meals": result.get("meals", []),
        }
    item_id = f"{kind}:{key}" if key else f"{kind}:{uuid4().hex}"
    with closing(connect()) as connection, connection:
        connection.execute(
            "INSERT OR REPLACE INTO memory_entries VALUES(?,?,?,?,?)",
            (item_id, user_id, kind, _now(), json.dumps(compact, ensure_ascii=False)),
        )
        connection.execute(
            "DELETE FROM memory_entries WHERE user_id=? AND id NOT IN (SELECT id FROM memory_entries WHERE user_id=? ORDER BY created_at DESC LIMIT 100)",
            (user_id, user_id),
        )


def recent_memory(user_id, limit=20):
    user_id = validate_user_id(user_id)
    limit = max(1, min(int(limit), 100))
    with closing(connect()) as connection:
        rows = connection.execute(
            "SELECT kind,created_at,payload FROM memory_entries WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [{"kind": kind, "created_at": stamp, **json.loads(payload)} for kind, stamp, payload in rows]


def save_chat_exchange(user_id, user_message, assistant_message):
    user_id = validate_user_id(user_id)
    if (not isinstance(user_message, str) or not isinstance(assistant_message, str)
            or len(user_message) > 2000 or len(assistant_message) > 8000):
        raise ValueError("聊天内容必须是文本。")
    with closing(connect()) as connection, connection:
        connection.executemany(
            "INSERT INTO chat_messages(user_id,created_at,role,content) VALUES(?,?,?,?)",
            [(user_id, _now(), "user", user_message), (user_id, _now(), "assistant", assistant_message)],
        )
        connection.execute(
            "DELETE FROM chat_messages WHERE user_id=? AND id NOT IN (SELECT id FROM chat_messages WHERE user_id=? ORDER BY id DESC LIMIT 80)",
            (user_id, user_id),
        )


def recent_chat(user_id, limit=12):
    user_id = validate_user_id(user_id)
    limit = max(2, min(int(limit), 40))
    with closing(connect()) as connection:
        rows = connection.execute(
            "SELECT role,content FROM chat_messages WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [{"role": role, "content": content} for role, content in reversed(rows)]


def memory_snapshot(user_id):
    user_id = validate_user_id(user_id)
    with closing(connect()) as connection:
        report_rows = connection.execute(
            "SELECT payload FROM reports WHERE user_id=? ORDER BY recorded_at DESC LIMIT 20", (user_id,)
        ).fetchall()
        profile_row = connection.execute("SELECT updated_at,payload FROM profiles WHERE user_id=?", (user_id,)).fetchone()
        counts = dict(connection.execute(
            "SELECT kind,COUNT(*) FROM memory_entries WHERE user_id=? GROUP BY kind", (user_id,)
        ).fetchall())
    return {
        "user_id": user_id,
        "profile": json.loads(profile_row[1]) if profile_row else {},
        "profile_updated_at": profile_row[0] if profile_row else None,
        "recent_reports": [json.loads(row[0]) for row in report_rows],
        "recent_records": recent_memory(user_id, 20),
        "chat_messages": recent_chat(user_id, 12),
        "record_counts": counts,
        "storage": "local_sqlite",
    }


def memory_context(user_id):
    snapshot = memory_snapshot(user_id)
    return {
        "profile": snapshot["profile"],
        "recent_records": snapshot["recent_records"][:12],
        "recent_reports": [
            {key: report.get(key) for key in (
                "session_id", "duration_minutes", "completed_exercises", "sets_completed",
                "reps_completed", "average_perceived_effort", "recovery_check",
                "reported_stop_symptom", "user_feedback",
            ) if key in report}
            for report in snapshot["recent_reports"][:10]
        ],
    }


def delete(user_id):
    user_id = validate_user_id(user_id)
    with closing(connect()) as connection, connection:
        for table in ("reports", "profiles", "memory_entries", "chat_messages"):
            connection.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))


def memory_overview(user_id):
    snapshot = memory_snapshot(user_id)
    return {key: snapshot[key] for key in (
        "user_id", "profile", "profile_updated_at", "recent_reports", "recent_records",
        "chat_messages", "record_counts", "storage",
    )}

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

DATABASE = Path(__file__).resolve().parents[1] / "data" / "history.sqlite3"


def connect():
    DATABASE.parent.mkdir(exist_ok=True)
    connection = sqlite3.connect(DATABASE, timeout=10)
    connection.execute("CREATE TABLE IF NOT EXISTS reports (user_id TEXT, session_id TEXT, recorded_at TEXT, payload TEXT, PRIMARY KEY(user_id, session_id))")
    return connection


def recent(user_id):
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id 必须是非空字符串")
    with closing(connect()) as connection:
        rows = connection.execute("SELECT payload FROM reports WHERE user_id=? ORDER BY recorded_at DESC LIMIT 20", (user_id,)).fetchall()
    return [json.loads(row[0]) for row in rows]


def save(user_id, report):
    recent(user_id)
    with closing(connect()) as connection, connection:
        connection.execute("INSERT INTO reports VALUES(?,?,?,?) ON CONFLICT(user_id,session_id) DO UPDATE SET payload=excluded.payload", (user_id, report["session_id"], datetime.now(timezone.utc).isoformat(), json.dumps(report, ensure_ascii=False)))


def delete(user_id):
    recent(user_id)
    with closing(connect()) as connection, connection:
        connection.execute("DELETE FROM reports WHERE user_id=?", (user_id,))

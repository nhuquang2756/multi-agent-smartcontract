"""Local SQLite persistence for browser-created research sessions."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
from contextlib import contextmanager
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


class SessionStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.environ.get(
            "MARLOWE_UI_DB", ROOT / "runs" / "marlowe-ui.sqlite3"
        )).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL,
                pending_json TEXT,
                result_json TEXT,
                error TEXT
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                event_id INTEGER NOT NULL,
                event_json TEXT NOT NULL,
                PRIMARY KEY(session_id, event_id)
            )""")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @contextmanager
    def _connection(self):
        db = self._connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, session_id: str, provider: str, model: str, prompt: str) -> None:
        with self._connection() as db:
            db.execute("INSERT INTO sessions(session_id,provider,model,prompt,status) VALUES(?,?,?,?,?)",
                       (session_id, provider, model, prompt, "STARTING"))

    def event(self, session_id: str, event: dict[str, Any]) -> None:
        with self._connection() as db:
            db.execute("INSERT OR REPLACE INTO events(session_id,event_id,event_json) VALUES(?,?,?)",
                       (session_id, event["id"], json.dumps(event, ensure_ascii=False)))

    def update(self, session_id: str, *, status: str, pending: dict[str, Any] | None,
               result: dict[str, Any] | None, error: str | None) -> None:
        with self._connection() as db:
            db.execute("""UPDATE sessions SET updated_at=CURRENT_TIMESTAMP,status=?,
                pending_json=?,result_json=?,error=? WHERE session_id=?""",
                       (status, _dump(pending), _dump(result), error, session_id))

    def detail(self, session_id: str) -> dict[str, Any] | None:
        with self._connection() as db:
            row = db.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
            if row is None:
                return None
            events = db.execute("SELECT event_json FROM events WHERE session_id=? ORDER BY event_id",
                                (session_id,)).fetchall()
        return {"session_id": row["session_id"], "status": row["status"],
                "created_at": row["created_at"], "updated_at": row["updated_at"],
                "provider": row["provider"], "model": row["model"], "prompt": row["prompt"],
                "events": [json.loads(item["event_json"]) for item in events],
                "pending": json.loads(row["pending_json"]) if row["pending_json"] else None,
                "result": json.loads(row["result_json"]) if row["result_json"] else None,
                "error": row["error"]}

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connection() as db:
            rows = db.execute("""SELECT session_id,created_at,updated_at,provider,model,prompt,status
                FROM sessions ORDER BY created_at DESC LIMIT ?""", (limit,)).fetchall()
        return [dict(row) for row in rows]


def _dump(value: Any) -> str | None:
    return json.dumps(value, ensure_ascii=False) if value is not None else None

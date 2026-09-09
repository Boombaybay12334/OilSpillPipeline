from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.core.config import DB_PATH


class InvestigationStore:
    def __init__(self, db_path: Path = DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS investigations (event_id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL, mode TEXT NOT NULL, created_at_utc TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS progress (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL, percent INTEGER, message TEXT NOT NULL, level TEXT NOT NULL, created_at_utc TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS artifacts (artifact_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, relative_path TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(event_id, relative_path));
            """)

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def save_event(self, event: dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO investigations VALUES (?, ?, ?, ?, ?, ?)", (event["event_id"], event["name"], event["status"], event["mode"], event["created_at_utc"], json.dumps(event)))

    def list_events(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM investigations ORDER BY created_at_utc DESC")]

    def emit(self, event_id: str, stage: str, status: str, message: str, percent: int | None = None, level: str = "INFO") -> dict[str, Any]:
        from app.services.data_manager import utc_now
        entry = {"event_id": event_id, "stage": stage, "status": status, "percent": percent, "message": message, "level": level, "created_at_utc": utc_now()}
        with self._connect() as db:
            db.execute("INSERT INTO progress(event_id, stage, status, percent, message, level, created_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?)", tuple(entry.values()))
        return entry

    def progress(self, event_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT event_id, stage, status, percent, message, level, created_at_utc FROM progress WHERE event_id=? ORDER BY id", (event_id,)).fetchall()
        keys = ("event_id", "stage", "status", "percent", "message", "level", "created_at_utc")
        return [dict(zip(keys, row)) for row in rows]

    def replace_artifacts(self, event_id: str, artifacts: list[dict[str, Any]]) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM artifacts WHERE event_id=?", (event_id,))
            db.executemany("INSERT INTO artifacts VALUES (?, ?, ?, ?)", [(a["artifact_id"], event_id, a["relative_path"], json.dumps(a)) for a in artifacts])

    def artifacts(self, event_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM artifacts WHERE event_id=? ORDER BY json_extract(payload, '$.display_priority') DESC", (event_id,))]
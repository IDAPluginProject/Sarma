"""Persistent storage for Sarma CLI sessions (per-workspace ./.sarma/db.sqlite)."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Any

from sarma_cli import paths

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    model_name  TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'idle',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    turn_id         TEXT NOT NULL DEFAULT '',
    role            TEXT NOT NULL,
    content         TEXT NOT NULL DEFAULT '',
    tool_name       TEXT,
    reasoning       TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE TABLE IF NOT EXISTS tool_executions (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    turn_id         TEXT NOT NULL DEFAULT '',
    server_name     TEXT NOT NULL DEFAULT '',
    tool_name       TEXT NOT NULL DEFAULT '',
    args_json       TEXT NOT NULL DEFAULT '',
    result_summary  TEXT,
    status          TEXT NOT NULL DEFAULT 'started',
    error_text      TEXT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE TABLE IF NOT EXISTS memory_artifacts (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    kind            TEXT NOT NULL DEFAULT 'structured_context',
    content         TEXT NOT NULL DEFAULT '',
    source_count    INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_tools_conv ON tool_executions(conversation_id);
CREATE INDEX IF NOT EXISTS idx_memory_conv ON memory_artifacts(conversation_id);
"""


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return uuid.uuid4().hex[:12]


class Store:
    """SQLite persistence for CLI audit sessions."""

    _CONVERSATION_UPDATE_FIELDS = {"title", "model_name", "status", "updated_at"}

    def __init__(self) -> None:
        db = paths.db_path()
        db.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA_SQL)

    def create_conversation(self, title: str = "", model_name: str = "") -> str:
        cid = _uid()
        now = _now_iso()
        self._conn.execute(
            "INSERT INTO conversations (id, title, model_name, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'idle', ?, ?)",
            (cid, title, model_name, now, now),
        )
        self._conn.commit()
        return cid

    def update_conversation(self, cid: str, **kw: Any) -> None:
        kw["updated_at"] = _now_iso()
        invalid = set(kw) - self._CONVERSATION_UPDATE_FIELDS
        if invalid:
            raise ValueError(f"Invalid conversation update field(s): {', '.join(sorted(invalid))}")
        sets = ", ".join(f"{k}=?" for k in kw)
        self._conn.execute(
            f"UPDATE conversations SET {sets} WHERE id=?",
            (*kw.values(), cid),
        )
        self._conn.commit()

    def list_conversations(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_conversation(self, cid: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM conversations WHERE id=?", (cid,),
        ).fetchone()
        return dict(row) if row else None

    def save_message(
        self, conversation_id: str, turn_id: str, role: str,
        content: str, tool_name: str | None = None, reasoning: str | None = None,
    ) -> str:
        mid = _uid()
        self._conn.execute(
            "INSERT INTO messages (id, conversation_id, turn_id, role, content, tool_name, reasoning, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (mid, conversation_id, turn_id, role, content, tool_name, reasoning, _now_iso()),
        )
        self._conn.commit()
        return mid

    def replace_messages(
        self,
        conversation_id: str,
        messages: list[Any],
    ) -> None:
        """Replace persisted replay history after context compaction."""
        now = _now_iso()
        with self._conn:
            self._conn.execute(
                "DELETE FROM messages WHERE conversation_id=?",
                (conversation_id,),
            )
            for message in messages:
                self._conn.execute(
                    "INSERT INTO messages "
                    "(id, conversation_id, turn_id, role, content, tool_name, "
                    "reasoning, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        getattr(message, "id", "") or _uid(),
                        conversation_id,
                        getattr(message, "turn_id", "") or "",
                        getattr(message, "role", "") or "",
                        getattr(message, "content", "") or "",
                        getattr(message, "tool_name", None),
                        getattr(message, "reasoning_content", None),
                        getattr(message, "created_at", "") or now,
                    ),
                )

    def load_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at",
            (conversation_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def save_memory_artifact(
        self,
        conversation_id: str,
        content: str,
        *,
        kind: str = "structured_context",
        source_count: int = 0,
    ) -> str:
        mid = _uid()
        self._conn.execute(
            "INSERT INTO memory_artifacts "
            "(id, conversation_id, kind, content, source_count, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                mid,
                conversation_id,
                kind,
                content,
                int(source_count),
                _now_iso(),
            ),
        )
        self._conn.commit()
        return mid

    def load_memory_artifacts(
        self,
        conversation_id: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memory_artifacts WHERE conversation_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def save_tool_execution(
        self, conversation_id: str, turn_id: str, tool_name: str,
        args_json: str, server_name: str = "",
    ) -> str:
        tid = _uid()
        self._conn.execute(
            "INSERT INTO tool_executions "
            "(id, conversation_id, turn_id, server_name, tool_name, args_json, status, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'started', ?)",
            (tid, conversation_id, turn_id, server_name, tool_name, args_json, _now_iso()),
        )
        self._conn.commit()
        return tid

    def finish_tool_execution(
        self, tid: str, status: str = "succeeded",
        result_summary: str | None = None, error_text: str | None = None,
    ) -> None:
        self._conn.execute(
            "UPDATE tool_executions SET status=?, result_summary=?, error_text=?, finished_at=? WHERE id=?",
            (status, result_summary, error_text, _now_iso(), tid),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

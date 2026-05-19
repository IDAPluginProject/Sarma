"""Lightweight database migration framework.

Extracts the incremental migration logic from database.py into a
structured, testable form. Each Migration has a version, name, and
the SQL to run. Migrations are applied in order and are idempotent
(guarded by PRAGMA table_info checks where needed).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class Migration:
    version: int
    name: str
    up: str  # SQL to execute (may be multi-statement)


def _col_exists(conn: sqlite3.Connection, table: str, col: str) -> bool:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    return col in cols


def _add_col_if_missing(
    conn: sqlite3.Connection, table: str, col: str, spec: str
) -> None:
    if not _col_exists(conn, table, col):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {spec}")


def apply_migrations(conn: sqlite3.Connection, current: int, target: int) -> None:
    """Apply all pending migrations from current+1 up to target."""
    if current >= target:
        return

    if current < 2:
        for col, spec in (
            ("transport", "TEXT NOT NULL DEFAULT 'stdio'"),
            ("command",   "TEXT NOT NULL DEFAULT ''"),
            ("args",      "TEXT NOT NULL DEFAULT ''"),
            ("env",       "TEXT NOT NULL DEFAULT ''"),
            ("cwd",       "TEXT NOT NULL DEFAULT ''"),
            ("headers",   "TEXT NOT NULL DEFAULT ''"),
            ("timeout",   "REAL NOT NULL DEFAULT 30.0"),
        ):
            _add_col_if_missing(conn, "mcp_servers", col, spec)

    if current < 3:
        for col, spec in (
            ("encoding",         "TEXT NOT NULL DEFAULT 'utf-8'"),
            ("sse_read_timeout", "REAL NOT NULL DEFAULT 300.0"),
        ):
            _add_col_if_missing(conn, "mcp_servers", col, spec)

    if current < 4:
        for col, spec in (
            ("version",      "TEXT NOT NULL DEFAULT ''"),
            ("file_path",    "TEXT NOT NULL DEFAULT ''"),
            ("install_dir",  "TEXT NOT NULL DEFAULT ''"),
            ("installed_at", "TEXT NOT NULL DEFAULT ''"),
        ):
            _add_col_if_missing(conn, "skills", col, spec)

    if current < 5:
        for col, spec in (
            ("system_prompt_template", "TEXT NOT NULL DEFAULT ''"),
            ("tool_allowlist_json",    "TEXT"),
            ("tool_denylist_json",     "TEXT"),
            ("model_override",         "TEXT NOT NULL DEFAULT ''"),
            ("temperature_override",   "REAL"),
        ):
            _add_col_if_missing(conn, "skills", col, spec)

    if current < 6:
        _add_col_if_missing(
            conn, "conversation_messages",
            "reasoning_content", "TEXT NOT NULL DEFAULT ''"
        )

    if current < 7:
        _add_col_if_missing(
            conn, "model_providers",
            "max_context_tokens", "INTEGER NOT NULL DEFAULT 0"
        )

    if current < 8:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workspace_history (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                path           TEXT    NOT NULL UNIQUE,
                name           TEXT    NOT NULL DEFAULT '',
                last_opened_at TEXT    NOT NULL DEFAULT ''
            )
        """)

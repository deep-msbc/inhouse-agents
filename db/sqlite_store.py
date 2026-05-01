"""
SQLite storage layer for persisting user-story extraction results.

Table: extracted_requirements
  - id              TEXT PRIMARY KEY  (UUID4)
  - user_story_id   TEXT NOT NULL     (identifies the user story / filename)
  - extracted_requirements  TEXT NOT NULL  (JSON blob)
  - created_at      TEXT NOT NULL     (ISO-8601 timestamp)
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

DB_PATH = Path(__file__).resolve().parent.parent / "database" / "extracted_requirements.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS extracted_requirements (
    id                      TEXT PRIMARY KEY,
    user_story_id           TEXT NOT NULL,
    extracted_requirements  TEXT NOT NULL,
    created_at              TEXT NOT NULL
);
"""

_CREATE_PLANNER_TABLE = """
CREATE TABLE IF NOT EXISTS planner_plans (
    id                   TEXT PRIMARY KEY,
    extraction_id        TEXT,
    plan_json            TEXT NOT NULL,
    usage_json           TEXT NOT NULL,
    created_at           TEXT NOT NULL
);
"""


@contextmanager
def _get_connection() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create all tables (and the database directory) if they don't already exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _get_connection() as conn:
        conn.execute(_CREATE_TABLE)
        conn.execute(_CREATE_PLANNER_TABLE)


def save_extraction(
    user_story_id: str,
    extracted_requirements: dict | list,
) -> str:
    """
    Persist an extraction result and return the generated UUID.

    Args:
        user_story_id: Identifier for the user story (e.g. filename).
        extracted_requirements: The JSON-serialisable extraction output.

    Returns:
        The UUID (str) of the newly inserted row.
    """
    row_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(extracted_requirements, ensure_ascii=False)

    with _get_connection() as conn:
        conn.execute(
            "INSERT INTO extracted_requirements (id, user_story_id, extracted_requirements, created_at) "
            "VALUES (?, ?, ?, ?)",
            (row_id, user_story_id, payload, now),
        )
    return row_id


def get_extraction_by_id(row_id: str) -> dict[str, Any] | None:
    """Fetch a single row by its UUID. Returns None if not found."""
    with _get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM extracted_requirements WHERE id = ?", (row_id,)
        )
        row = cur.fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def get_extractions_by_story(user_story_id: str) -> list[dict[str, Any]]:
    """Fetch all rows for a given user_story_id, newest first."""
    with _get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM extracted_requirements WHERE user_story_id = ? ORDER BY created_at DESC",
            (user_story_id,),
        )
        rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]


def get_latest_extraction(user_story_id: str) -> dict[str, Any] | None:
    """Fetch the most recent extraction for a given user story."""
    with _get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM extracted_requirements WHERE user_story_id = ? ORDER BY created_at DESC LIMIT 1",
            (user_story_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def get_most_recent_extraction() -> dict[str, Any] | None:
    """Fetch the most recently saved extraction regardless of user_story_id."""
    with _get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM extracted_requirements ORDER BY created_at DESC LIMIT 1"
        )
        row = cur.fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def save_plan(
    plan: list | dict,
    usage: dict | None = None,
    extraction_id: str | None = None,
) -> str:
    """
    Persist a planner output and return the generated UUID.

    Args:
        plan: The JSON-serialisable planner output (list of module plans or full dict).
        usage: Optional token-usage dict (from LLMUsage.model_dump()).
        extraction_id: Optional UUID of the related extracted_requirements row.

    Returns:
        The UUID (str) of the newly inserted row.
    """
    row_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    plan_payload = json.dumps(plan, ensure_ascii=False)
    usage_payload = json.dumps(usage or {}, ensure_ascii=False)

    with _get_connection() as conn:
        conn.execute(
            "INSERT INTO planner_plans (id, extraction_id, plan_json, usage_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (row_id, extraction_id, plan_payload, usage_payload, now),
        )
    return row_id


def get_plan(plan_id: str) -> dict[str, Any] | None:
    """Fetch a planner plan by its UUID. Returns dict with 'plan' and 'usage' keys."""
    with _get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM planner_plans WHERE id = ?", (plan_id,)
        )
        row = cur.fetchone()
    if row is None:
        return None
    d = dict(row)
    d["plan"] = json.loads(d["plan_json"])
    d["usage"] = json.loads(d["usage_json"])
    return d


def get_latest_plan() -> dict[str, Any] | None:
    """Fetch the most recent planner plan."""
    with _get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM planner_plans ORDER BY created_at DESC LIMIT 1"
        )
        row = cur.fetchone()
    if row is None:
        return None
    d = dict(row)
    d["plan"] = json.loads(d["plan_json"])
    d["usage"] = json.loads(d["usage_json"])
    return d


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["extracted_requirements"] = json.loads(d["extracted_requirements"])
    return d


# Auto-create tables on import
init_db()

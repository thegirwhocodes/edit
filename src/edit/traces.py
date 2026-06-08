"""Lightweight trace store — every chat turn lands here for cost auditing.

One SQLite file (`traces.db`) per project root. Sits alongside `memory.db`.
The user can inspect, export, or delete it without touching memory.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any


_DB = "traces.db"


def _project_root() -> Path:
    return Path(os.environ.get("EDIT_PROJECT_ROOT", os.getcwd())).resolve()


def _db_path() -> Path:
    p = _project_root() / _DB
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


_SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
  id TEXT PRIMARY KEY,
  started_at INTEGER NOT NULL,
  ended_at INTEGER,
  brief TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'running',  -- 'running'|'done'|'error'
  cost_usd REAL DEFAULT 0,
  input_tokens INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,
  tool_calls INTEGER DEFAULT 0,
  output_files TEXT,                        -- JSON array of paths
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_traces_started ON traces(started_at DESC);
"""


def _conn() -> sqlite3.Connection:
    db = sqlite3.connect(_db_path())
    db.row_factory = sqlite3.Row
    db.executescript(_SCHEMA)
    return db


def start_trace(trace_id: str, brief: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO traces(id, started_at, brief) VALUES(?, ?, ?)",
            (trace_id, int(time.time()), brief),
        )


def finish_trace(
    trace_id: str,
    *,
    cost_usd: float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    tool_calls: int = 0,
    output_files: list[str] | None = None,
    status: str = "done",
    error: str | None = None,
) -> None:
    with _conn() as c:
        c.execute(
            """UPDATE traces SET
                ended_at = ?,
                status = ?,
                cost_usd = COALESCE(?, cost_usd),
                input_tokens = COALESCE(?, input_tokens),
                output_tokens = COALESCE(?, output_tokens),
                tool_calls = ?,
                output_files = ?,
                error = ?
               WHERE id = ?""",
            (
                int(time.time()),
                status,
                cost_usd,
                input_tokens,
                output_tokens,
                tool_calls,
                json.dumps(output_files or []),
                error,
                trace_id,
            ),
        )


def recent_traces(limit: int = 50) -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM traces ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def session_totals() -> dict[str, Any]:
    """Lifetime totals — for the cost pill in the UI."""
    with _conn() as c:
        row = c.execute(
            """SELECT
                COUNT(*) AS n,
                COALESCE(SUM(cost_usd), 0) AS total_cost,
                COALESCE(SUM(input_tokens), 0) AS total_in,
                COALESCE(SUM(output_tokens), 0) AS total_out
               FROM traces"""
        ).fetchone()
    return dict(row) if row else {"n": 0, "total_cost": 0, "total_in": 0, "total_out": 0}


def today_totals() -> dict[str, Any]:
    """Today's totals — for budget enforcement at the UI level."""
    today_start = int(time.time()) - 24 * 3600  # rolling 24h is more useful than calendar day
    with _conn() as c:
        row = c.execute(
            """SELECT
                COUNT(*) AS n,
                COALESCE(SUM(cost_usd), 0) AS total_cost
               FROM traces WHERE started_at >= ?""",
            (today_start,),
        ).fetchone()
    return dict(row) if row else {"n": 0, "total_cost": 0}

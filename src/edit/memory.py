"""SQLite-backed memory for Ed.it.

One file (`memory.db`) under the project root. Symbolic facts (preferences,
profile) live in plain tables. Episodic text + style notes live in a `memory_items`
table indexed by FTS5 for fast keyword recall. A vector layer can be bolted on
later (sqlite-vec) without changing the public API — `recall` already has
room for an `embedding` filter.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any


_DB_FILE = "memory.db"


def _project_root() -> Path:
    return Path(os.environ.get("EDIT_PROJECT_ROOT", os.getcwd())).resolve()


def _db_path() -> Path:
    p = _project_root() / _DB_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_profile (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS preferences (
  id INTEGER PRIMARY KEY,
  scope TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0.8,
  source TEXT NOT NULL DEFAULT 'explicit',
  supersedes INTEGER,
  superseded_by INTEGER,
  valid_from INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prefs_active
  ON preferences(scope, key) WHERE superseded_by IS NULL;

CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  folder_path TEXT,
  mode TEXT,
  created_at INTEGER NOT NULL,
  last_touched_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  project_id INTEGER,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_project_ts
  ON events(project_id, ts DESC);

CREATE TABLE IF NOT EXISTS memory_items (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  text TEXT NOT NULL,
  project_id INTEGER,
  confidence REAL NOT NULL DEFAULT 1.0,
  access_count INTEGER NOT NULL DEFAULT 0,
  last_accessed_at INTEGER,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mem_kind
  ON memory_items(kind, project_id);

-- FTS5 virtual table for keyword recall (fast even at 50k+ rows)
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
  text, kind, content='memory_items', content_rowid='id'
);

-- Keep FTS5 in sync with the items table
CREATE TRIGGER IF NOT EXISTS memory_items_ai AFTER INSERT ON memory_items BEGIN
  INSERT INTO memory_fts(rowid, text, kind) VALUES (new.id, new.text, new.kind);
END;
CREATE TRIGGER IF NOT EXISTS memory_items_ad AFTER DELETE ON memory_items BEGIN
  INSERT INTO memory_fts(memory_fts, rowid, text, kind) VALUES('delete', old.id, old.text, old.kind);
END;
CREATE TRIGGER IF NOT EXISTS memory_items_au AFTER UPDATE ON memory_items BEGIN
  INSERT INTO memory_fts(memory_fts, rowid, text, kind) VALUES('delete', old.id, old.text, old.kind);
  INSERT INTO memory_fts(rowid, text, kind) VALUES (new.id, new.text, new.kind);
END;
"""


def _conn() -> sqlite3.Connection:
    db = sqlite3.connect(_db_path())
    db.row_factory = sqlite3.Row
    db.executescript(_SCHEMA)
    return db


# ----------- Public API used by the tool layer and by `core_memory_block` -----------

def write_profile(key: str, value: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO user_profile(key, value, updated_at) VALUES(?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, int(time.time())),
        )


def read_profile() -> dict[str, str]:
    with _conn() as c:
        rows = c.execute("SELECT key, value FROM user_profile").fetchall()
    return {r["key"]: r["value"] for r in rows}


def set_preference(scope: str, key: str, value: str, *, confidence: float = 0.9, source: str = "explicit") -> None:
    now = int(time.time())
    with _conn() as c:
        # Supersede any current active value for this (scope, key)
        existing = c.execute(
            "SELECT id FROM preferences WHERE scope=? AND key=? AND superseded_by IS NULL",
            (scope, key),
        ).fetchone()
        cur = c.execute(
            "INSERT INTO preferences(scope, key, value, confidence, source, supersedes, valid_from) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (scope, key, value, confidence, source, existing["id"] if existing else None, now),
        )
        if existing:
            c.execute("UPDATE preferences SET superseded_by=? WHERE id=?", (cur.lastrowid, existing["id"]))


def list_preferences(scope: str | None = None) -> list[dict[str, Any]]:
    sql = (
        "SELECT scope, key, value, confidence, source FROM preferences "
        "WHERE superseded_by IS NULL"
    )
    args: tuple[Any, ...] = ()
    if scope:
        sql += " AND scope = ?"
        args = (scope,)
    sql += " ORDER BY confidence DESC, scope, key"
    with _conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def write_memory(kind: str, text: str, *, project_id: int | None = None, confidence: float = 1.0) -> int:
    now = int(time.time())
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO memory_items(kind, text, project_id, confidence, created_at) "
            "VALUES(?, ?, ?, ?, ?)",
            (kind, text, project_id, confidence, now),
        )
        return cur.lastrowid or 0


def recall_memory(query: str, *, kind: str | None = None, k: int = 8) -> list[dict[str, Any]]:
    """FTS5 keyword recall. Falls back to LIKE if FTS isn't available for any reason."""
    with _conn() as c:
        try:
            sql = (
                "SELECT i.id, i.kind, i.text, i.project_id, i.confidence, i.created_at "
                "FROM memory_fts f JOIN memory_items i ON i.id = f.rowid "
                "WHERE memory_fts MATCH ? "
            )
            args: list[Any] = [query]
            if kind:
                sql += "AND i.kind = ? "
                args.append(kind)
            sql += "ORDER BY rank LIMIT ?"
            args.append(k)
            rows = c.execute(sql, args).fetchall()
        except sqlite3.OperationalError:
            # FTS5 not available (rare) — fall back to LIKE
            sql = "SELECT * FROM memory_items WHERE text LIKE ? "
            args = [f"%{query}%"]
            if kind:
                sql += "AND kind = ? "
                args.append(kind)
            sql += "ORDER BY created_at DESC LIMIT ?"
            args.append(k)
            rows = c.execute(sql, args).fetchall()

        out: list[dict[str, Any]] = []
        now = int(time.time())
        for r in rows:
            out.append(dict(r))
            c.execute(
                "UPDATE memory_items SET access_count = access_count + 1, last_accessed_at = ? WHERE id = ?",
                (now, r["id"]),
            )
        return out


def log_event(kind: str, payload: dict[str, Any], *, project_id: int | None = None) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO events(project_id, kind, payload_json, ts) VALUES(?, ?, ?, ?)",
            (project_id, kind, json.dumps(payload, ensure_ascii=False), int(time.time())),
        )


def core_memory_block(max_chars: int = 2000) -> str:
    """Auto-assemble the always-on memory block injected into the agent's system prompt.

    Profile facts first, then top preferences. Hard-capped — the production
    research is explicit: every token in the system prompt is paid on every turn.
    """
    profile = read_profile()
    prefs = list_preferences()[:20]

    lines: list[str] = []
    if profile:
        lines.append("## What I know about you")
        for k, v in sorted(profile.items()):
            lines.append(f"- {k}: {v}")
    if prefs:
        lines.append("\n## Your preferences (most-confident first)")
        by_scope: dict[str, list[str]] = {}
        for p in prefs:
            by_scope.setdefault(p["scope"], []).append(f'  - {p["key"]}: {p["value"]}')
        for scope, items in by_scope.items():
            lines.append(f"- *{scope}*")
            lines.extend(items)

    block = "\n".join(lines)
    if len(block) > max_chars:
        block = block[:max_chars].rsplit("\n", 1)[0] + "\n…"
    return block

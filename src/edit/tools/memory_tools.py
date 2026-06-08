"""Memory tools exposed to the agent.

Per the research: memory-as-tools (explicit recall/write) beats auto-RAG
because the model controls what it remembers and you can audit every write.
"""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import tool

from .. import memory
from ._safe import ToolError


def _content(payload: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


@tool(
    "memory_recall",
    (
        "Look up things you've learned about the user from past sessions: "
        "preferences, past edits, brand style, project history. Returns up to "
        "k items matching the keyword query. Use this before making a "
        "stylistic decision the user might already have an opinion on."
    ),
    {"query": str, "kind": str, "k": int},
)
async def memory_recall(args: dict[str, Any]) -> dict[str, Any]:
    try:
        query = args.get("query", "").strip()
        if not query:
            raise ToolError("missing_query", "Query is empty.", "Pass a keyword phrase like 'caption style' or 'worship'.")
        kind = args.get("kind") or None
        k = int(args.get("k") or 8)
        items = memory.recall_memory(query, kind=kind, k=k)
        return _content({"status": "ok", "count": len(items), "items": items})
    except ToolError as e:
        return _content(e.to_payload())


@tool(
    "memory_write",
    (
        "Save a durable fact about the user for future sessions. Use sparingly — "
        "only when the user expresses a preference ('I like…', 'always…'), "
        "an identity fact ('I'm a worship leader'), or you observe the same "
        "explicit choice 3+ times. Kinds: 'preference' | 'identity' | "
        "'project_note' | 'style_example'."
    ),
    {"kind": str, "text": str, "confidence": float},
)
async def memory_write(args: dict[str, Any]) -> dict[str, Any]:
    try:
        kind = args.get("kind", "").strip()
        text = args.get("text", "").strip()
        if not kind or not text:
            raise ToolError("missing_fields", "Both kind and text are required.", "")
        confidence = float(args.get("confidence") or 1.0)
        rid = memory.write_memory(kind, text, confidence=confidence)
        return _content({"status": "ok", "id": rid, "kind": kind})
    except ToolError as e:
        return _content(e.to_payload())


@tool(
    "preference_set",
    (
        "Record a structured preference. Use when the user states a specific "
        "preference for a scope ('worship', 'talking_head', 'lifestyle', "
        "'global'). Example: scope='worship', key='lut', value='Warm Cinematic'."
    ),
    {"scope": str, "key": str, "value": str, "confidence": float},
)
async def preference_set(args: dict[str, Any]) -> dict[str, Any]:
    try:
        scope = (args.get("scope") or "global").strip()
        key = args.get("key", "").strip()
        value = args.get("value", "").strip()
        if not key or not value:
            raise ToolError("missing_fields", "key and value are required.", "")
        confidence = float(args.get("confidence") or 0.9)
        memory.set_preference(scope, key, value, confidence=confidence, source="explicit")
        return _content({"status": "ok", "scope": scope, "key": key, "value": value})
    except ToolError as e:
        return _content(e.to_payload())


@tool(
    "profile_write",
    (
        "Record an identity fact about the user (name, role, content niche, "
        "brand voice). Always loaded into context for every future session."
    ),
    {"key": str, "value": str},
)
async def profile_write(args: dict[str, Any]) -> dict[str, Any]:
    try:
        key = args.get("key", "").strip()
        value = args.get("value", "").strip()
        if not key or not value:
            raise ToolError("missing_fields", "key and value are required.", "")
        memory.write_profile(key, value)
        return _content({"status": "ok", "key": key, "value": value})
    except ToolError as e:
        return _content(e.to_payload())

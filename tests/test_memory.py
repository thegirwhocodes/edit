"""Unit tests for the memory layer + memory tools."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_root(tmp_path: Path, monkeypatch):
    """Every test gets a fresh project root → fresh memory.db."""
    monkeypatch.setenv("EDIT_PROJECT_ROOT", str(tmp_path))
    yield


def test_profile_round_trip():
    from edit import memory
    memory.write_profile("name", "Naomi")
    memory.write_profile("role", "worship creator")
    assert memory.read_profile() == {"name": "Naomi", "role": "worship creator"}


def test_preference_supersedes():
    from edit import memory
    memory.set_preference("worship", "lut", "Warm v1", confidence=0.8)
    memory.set_preference("worship", "lut", "Warm v2", confidence=0.95)
    active = memory.list_preferences("worship")
    assert len(active) == 1
    assert active[0]["value"] == "Warm v2"
    assert active[0]["confidence"] == 0.95


def test_memory_write_and_recall():
    from edit import memory
    memory.write_memory("preference", "prefers warm cinematic edits")
    memory.write_memory("project_note", "Sunday Worship is filmed at 5pm")
    memory.write_memory("style_example", "bold Submagic captions for talking head")

    hits = memory.recall_memory("warm")
    assert any("warm" in h["text"].lower() for h in hits)

    hits_filtered = memory.recall_memory("captions", kind="style_example")
    assert all(h["kind"] == "style_example" for h in hits_filtered)


def test_core_memory_block_assembly():
    from edit import memory
    memory.write_profile("name", "Naomi")
    memory.set_preference("worship", "lut", "Naomi_Worship_Warm")
    block = memory.core_memory_block()
    assert "Naomi" in block
    assert "worship" in block
    assert "Naomi_Worship_Warm" in block


def _payload(result):
    """Tools return {content: [{type: text, text: json-string}]}."""
    return json.loads(result["content"][0]["text"])


def test_memory_tools_via_decorator():
    """Exercise the @tool-decorated entry points exactly as the agent does."""
    from edit.tools.memory_tools import (
        memory_recall,
        memory_write,
        preference_set,
        profile_write,
    )

    # Use .handler when the decorator wraps the coroutine, else call directly
    async def call(t, args):
        fn = getattr(t, "handler", t)
        return await fn(args)

    async def run():
        r = await call(profile_write, {"key": "name", "value": "Naomi"})
        assert _payload(r)["status"] == "ok"

        r = await call(preference_set, {
            "scope": "worship", "key": "captions", "value": "Submagic-style",
        })
        assert _payload(r)["status"] == "ok"

        r = await call(memory_write, {
            "kind": "style_example", "text": "loves warm cinematic worship cuts",
        })
        assert _payload(r)["status"] == "ok"

        r = await call(memory_recall, {"query": "warm"})
        payload = _payload(r)
        assert payload["status"] == "ok"
        assert payload["count"] >= 1

    asyncio.run(run())

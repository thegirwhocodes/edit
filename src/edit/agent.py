"""Main agent loop — wraps the Claude Agent SDK with Ed.it's tool set.

Memory is injected as the dynamic tail of the system prompt; the static head
sits before it so prompt caching covers the bulk of the bytes. If the user
has the DaVinci Resolve MCP server installed and EDIT_USE_RESOLVE=1, we
attach it alongside our in-process tools.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, AsyncIterator

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    create_sdk_mcp_server,
)

from .prompts import build_system_prompt
from .tools import ALL_TOOLS


def _maybe_resolve_server() -> dict[str, Any]:
    """If the user opts in, attach the existing DaVinci Resolve MCP server."""
    if not os.environ.get("EDIT_USE_RESOLVE"):
        return {}

    # Standard install path on Naomi's machine
    default_path = Path.home() / "Social Media" / "davinci-resolve-mcp"
    resolve_root = Path(os.environ.get("RESOLVE_MCP_PATH", default_path))
    server_py = resolve_root / "src" / "server.py"
    venv_py = resolve_root / "venv" / "bin" / "python"

    if not server_py.exists() or not venv_py.exists():
        return {}

    return {
        "davinci-resolve": {
            "type": "stdio",
            "command": str(venv_py),
            "args": [str(server_py)],
        }
    }


def _build_options() -> ClaudeAgentOptions:
    # Bundle in-process tools into one SDK MCP server.
    server = create_sdk_mcp_server(
        name="edit-tools",
        version="0.2.0",
        tools=ALL_TOOLS,
    )

    mcp_servers: dict[str, Any] = {"edit-tools": server}
    mcp_servers.update(_maybe_resolve_server())

    # Allowed tools: our in-process set, plus any external MCP tools the
    # SDK auto-discovers from the additional servers.
    allowed = [f"mcp__edit-tools__{t.name}" for t in ALL_TOOLS]
    if "davinci-resolve" in mcp_servers:
        # We don't know Resolve's full tool list at startup; allow the namespace.
        allowed.append("mcp__davinci-resolve__*")

    return ClaudeAgentOptions(
        system_prompt=build_system_prompt(),
        mcp_servers=mcp_servers,
        allowed_tools=allowed,
        model=os.environ.get("EDIT_MODEL", "claude-sonnet-4-5"),
        max_turns=int(os.environ.get("EDIT_MAX_TURNS", "30")),
        max_budget_usd=float(os.environ.get("EDIT_COST_BUDGET_USD", "3.0")),
        thinking={"type": "enabled", "budget_tokens": 4000},
    )


async def run_once(prompt: str) -> AsyncIterator:
    """Single-turn convenience: send a prompt, stream the response back."""
    async with ClaudeSDKClient(options=_build_options()) as client:
        await client.query(prompt)
        async for msg in client.receive_response():
            yield msg

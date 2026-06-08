"""Main agent loop — wraps the Claude Agent SDK with Ed.it's tool set."""

from __future__ import annotations

import os
from typing import AsyncIterator

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    create_sdk_mcp_server,
)

from .prompts import SYSTEM_PROMPT
from .tools import ALL_TOOLS


def _build_options() -> ClaudeAgentOptions:
    # Bundle all our @tool functions into one in-process MCP server.
    server = create_sdk_mcp_server(
        name="edit-tools",
        version="0.1.0",
        tools=ALL_TOOLS,
    )

    # The allowed-tools list uses the SDK's MCP tool-naming convention:
    # `mcp__<server_name>__<tool_name>`.
    allowed = [f"mcp__edit-tools__{t.name}" for t in ALL_TOOLS]

    return ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={"edit-tools": server},
        allowed_tools=allowed,
        model=os.environ.get("EDIT_MODEL", "claude-sonnet-4-5"),
        max_turns=int(os.environ.get("EDIT_MAX_TURNS", "30")),
        max_budget_usd=float(os.environ.get("EDIT_COST_BUDGET_USD", "3.0")),
        # Extended thinking helps the agent plan multi-step edits without
        # surfacing raw scratchpad to the user.
        thinking={"type": "enabled", "budget_tokens": 4000},
    )


async def run_once(prompt: str) -> AsyncIterator:
    """Single-turn convenience: send a prompt, stream the response back."""
    async with ClaudeSDKClient(options=_build_options()) as client:
        await client.query(prompt)
        async for msg in client.receive_response():
            yield msg
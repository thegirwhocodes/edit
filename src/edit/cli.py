"""CLI entry point for Ed.it.

Usage:
    edit "trim the first 30 seconds of input.mp4 into out/teaser.mp4"
    edit --root ~/Movies/MyProject "make a 9:16 reel from the highlight"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from .agent import run_once


console = Console()


def _load_env() -> None:
    """Load env from Ed.it/.env, then fall back to the cortex trove for keys."""
    here = Path(__file__).resolve().parent.parent.parent  # Ed.it/
    local = here / ".env"
    if local.exists():
        load_dotenv(local)
    # Fallback to Naomi's reusable credentials trove
    cortex = Path("/Users/naomiivie/cortex/cortex-web/.env.local")
    if cortex.exists() and not os.environ.get("ANTHROPIC_API_KEY"):
        load_dotenv(cortex, override=False)


def _render_message(msg) -> None:
    """Render an SDK message to the console.

    The SDK yields a heterogeneous stream — we pattern-match on attributes
    rather than concrete classes to stay version-tolerant.
    """
    kind = type(msg).__name__

    # Text + thinking blocks live on AssistantMessage.content
    content = getattr(msg, "content", None)
    if content:
        for block in content:
            btype = type(block).__name__
            if btype == "TextBlock":
                console.print(block.text, end="")
            elif btype == "ThinkingBlock":
                # Dim, single-line preview; users can see we're working
                preview = (block.thinking or "").replace("\n", " ")[:120]
                console.print(f"\n[dim italic]thinking: {preview}…[/dim italic]")
            elif btype == "ToolUseBlock":
                tool_name = block.name.replace("mcp__edit-tools__", "")
                args_preview = json.dumps(block.input, ensure_ascii=False)[:160]
                console.print(f"\n[cyan]→ {tool_name}[/cyan] [dim]{args_preview}[/dim]")
            elif btype == "ToolResultBlock":
                # Try to extract status from the JSON payload
                try:
                    text = block.content[0].text if block.content else "{}"
                    payload = json.loads(text)
                    status = payload.get("status", "?")
                    color = "green" if status == "ok" else "red"
                    if status == "error":
                        console.print(
                            f"  [{color}]✗ {payload.get('code')}[/{color}] "
                            f"{payload.get('message')}"
                        )
                        if payload.get("hint"):
                            console.print(f"  [dim]hint: {payload['hint']}[/dim]")
                    else:
                        # Show the most informative field per tool
                        head = payload.get("output_path") or payload.get("answer") \
                            or f"duration={payload.get('duration_sec')}"
                        if isinstance(head, str) and len(head) > 200:
                            head = head[:200] + "…"
                        console.print(f"  [{color}]✓[/{color}] {head}")
                except Exception:
                    console.print(f"  [dim]{block!r}[/dim]")

    # ResultMessage at end-of-turn carries usage / cost
    if kind == "ResultMessage":
        usage = getattr(msg, "usage", None)
        cost = getattr(msg, "total_cost_usd", None)
        if usage or cost is not None:
            bits = []
            if cost is not None:
                bits.append(f"cost ${cost:.4f}")
            if usage:
                if isinstance(usage, dict):
                    in_t = usage.get("input_tokens")
                    out_t = usage.get("output_tokens")
                else:
                    in_t = getattr(usage, "input_tokens", None)
                    out_t = getattr(usage, "output_tokens", None)
                if in_t is not None and out_t is not None:
                    bits.append(f"{in_t} in / {out_t} out")
            console.print(f"\n[dim]── {' · '.join(bits)}[/dim]")


async def _run(prompt: str) -> None:
    console.print(Panel(prompt, title="brief", border_style="dim"))
    async for msg in run_once(prompt):
        _render_message(msg)
    console.print()  # final newline


def main() -> int:
    parser = argparse.ArgumentParser(prog="edit", description="Ed.it CLI")
    parser.add_argument("prompt", nargs="+", help="Editing brief")
    parser.add_argument(
        "--root", default=None,
        help="Project root the agent is sandboxed to (default: cwd)",
    )
    args = parser.parse_args()

    _load_env()
    if args.root:
        os.environ["EDIT_PROJECT_ROOT"] = str(Path(args.root).expanduser().resolve())

    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("[red]ANTHROPIC_API_KEY is not set.[/red] Add it to Ed.it/.env or your shell.")
        return 2

    prompt = " ".join(args.prompt)
    try:
        asyncio.run(_run(prompt))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())

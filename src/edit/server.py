"""Web UI for Ed.it — FastAPI server wrapping the agent loop with SSE streaming.

Run:
    edit-web --root ~/Movies/MyProject
    # then open http://localhost:8765
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from .agent import run_once
from . import traces


HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"

# Daily soft budget — UI surfaces a warning when approached, hard-stop in agent.
BUDGET_USD = float(os.environ.get("EDIT_DAILY_BUDGET_USD", "5.0"))


def _load_env() -> None:
    here = HERE.parent.parent  # Ed.it/
    local = here / ".env"
    if local.exists():
        load_dotenv(local)
    cortex = Path("/Users/naomiivie/cortex/cortex-web/.env.local")
    if cortex.exists() and not os.environ.get("ANTHROPIC_API_KEY"):
        load_dotenv(cortex, override=False)


def _project_root() -> Path:
    return Path(os.environ.get("EDIT_PROJECT_ROOT", os.getcwd())).expanduser().resolve()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def create_app() -> FastAPI:
    app = FastAPI(title="Ed.it", version="0.1.0")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        html = (STATIC_DIR / "index.html").read_text()
        return HTMLResponse(html)

    @app.get("/health")
    async def health() -> dict:
        return {
            "ok": True,
            "project_root": str(_project_root()),
            "has_anthropic_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "has_gemini_key": bool(os.environ.get("GEMINI_API_KEY")),
        }

    @app.post("/upload")
    async def upload(file: UploadFile = File(...)) -> dict:
        root = _project_root()
        inbox = root / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        # Unique filename to avoid clobbering
        ext = Path(file.filename or "clip.mov").suffix or ".mov"
        name = f"{uuid.uuid4().hex[:8]}_{Path(file.filename or 'clip').stem}{ext}"
        dest = inbox / name
        size = 0
        with dest.open("wb") as f:
            while chunk := await file.read(1 << 20):  # 1 MB chunks
                f.write(chunk)
                size += len(chunk)
        return {
            "ok": True,
            "path": str(dest.relative_to(root)),
            "abs_path": str(dest),
            "size_bytes": size,
        }

    @app.get("/download")
    async def download(path: str) -> FileResponse:
        root = _project_root()
        target = (root / path).resolve()
        # Sandbox: refuse anything outside the project root
        if not str(target).startswith(str(root)):
            raise HTTPException(status_code=403, detail="path outside project root")
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="file not found")
        return FileResponse(target, filename=target.name)

    @app.post("/chat")
    async def chat(prompt: str = Form(...), file: str | None = Form(None)) -> StreamingResponse:
        """Stream the agent's tool calls, thinking, and text as SSE events."""
        # Soft budget check — return a 402 if today's spend already exceeds cap.
        today = traces.today_totals()
        if today["total_cost"] >= BUDGET_USD:
            async def deny():
                yield _sse("error", {
                    "message": f"Daily budget exceeded (${today['total_cost']:.2f} of ${BUDGET_USD:.2f}). "
                               "Raise EDIT_DAILY_BUDGET_USD to continue.",
                    "type": "BudgetExceeded",
                })
            return StreamingResponse(deny(), media_type="text/event-stream")

        full_brief = prompt
        if file:
            full_brief = f"The user uploaded `{file}` (relative to the project root). {prompt}"

        return StreamingResponse(_stream_agent(full_brief), media_type="text/event-stream")

    @app.get("/budget")
    async def budget() -> dict:
        today = traces.today_totals()
        lifetime = traces.session_totals()
        return {
            "cap_usd": BUDGET_USD,
            "today_usd": round(today["total_cost"], 4),
            "today_count": today["n"],
            "lifetime_usd": round(lifetime["total_cost"], 4),
            "lifetime_count": lifetime["n"],
            "remaining_usd": round(max(0.0, BUDGET_USD - today["total_cost"]), 4),
        }

    @app.get("/sessions")
    async def sessions(limit: int = 50) -> dict:
        return {"traces": traces.recent_traces(limit=limit)}

    return app


async def _stream_agent(brief: str) -> AsyncIterator[str]:
    """Translate SDK message objects into typed SSE events for the UI."""
    trace_id = uuid.uuid4().hex
    traces.start_trace(trace_id, brief)
    yield _sse("brief", {"text": brief, "trace_id": trace_id})

    tool_call_count = 0
    output_files: list[str] = []
    final_cost: float | None = None
    final_in: int | None = None
    final_out: int | None = None
    finished = False

    try:
        async for msg in run_once(brief):
            kind = type(msg).__name__
            content = getattr(msg, "content", None)
            if content:
                for block in content:
                    btype = type(block).__name__
                    if btype == "TextBlock":
                        yield _sse("text", {"text": block.text})
                    elif btype == "ThinkingBlock":
                        preview = (block.thinking or "").replace("\n", " ")[:200]
                        yield _sse("thinking", {"text": preview})
                    elif btype == "ToolUseBlock":
                        tool_call_count += 1
                        tool_name = block.name.replace("mcp__edit-tools__", "")
                        yield _sse("tool_start", {
                            "id": block.id,
                            "name": tool_name,
                            "args": block.input,
                        })
                    elif btype == "ToolResultBlock":
                        try:
                            text = block.content[0].text if block.content else "{}"
                            payload = json.loads(text)
                        except Exception:
                            payload = {"raw": repr(block)}
                        if isinstance(payload, dict) and payload.get("output_path"):
                            output_files.append(str(payload["output_path"]))
                        yield _sse("tool_result", {
                            "id": getattr(block, "tool_use_id", None),
                            "payload": payload,
                        })
            if kind == "ResultMessage":
                usage = getattr(msg, "usage", None)
                cost = getattr(msg, "total_cost_usd", None)
                final_cost = cost
                summary = {"cost_usd": cost, "trace_id": trace_id}
                if usage:
                    if isinstance(usage, dict):
                        final_in = usage.get("input_tokens")
                        final_out = usage.get("output_tokens")
                    else:
                        final_in = getattr(usage, "input_tokens", None)
                        final_out = getattr(usage, "output_tokens", None)
                    summary["input_tokens"] = final_in
                    summary["output_tokens"] = final_out
                yield _sse("done", summary)

        traces.finish_trace(
            trace_id,
            cost_usd=final_cost,
            input_tokens=final_in,
            output_tokens=final_out,
            tool_calls=tool_call_count,
            output_files=output_files,
            status="done",
        )
        finished = True
    except Exception as e:
        traces.finish_trace(
            trace_id,
            cost_usd=final_cost,
            input_tokens=final_in,
            output_tokens=final_out,
            tool_calls=tool_call_count,
            output_files=output_files,
            status="error",
            error=f"{type(e).__name__}: {e}",
        )
        yield _sse("error", {"message": str(e), "type": type(e).__name__})
        finished = True
    finally:
        # Client disconnects mid-stream still need to land in the trace store.
        if not finished:
            traces.finish_trace(
                trace_id,
                cost_usd=final_cost,
                input_tokens=final_in,
                output_tokens=final_out,
                tool_calls=tool_call_count,
                output_files=output_files,
                status="aborted",
            )


def main() -> int:
    parser = argparse.ArgumentParser(prog="edit-web", description="Ed.it web UI")
    parser.add_argument("--root", default=None, help="Project root the agent is sandboxed to")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    _load_env()
    if args.root:
        os.environ["EDIT_PROJECT_ROOT"] = str(Path(args.root).expanduser().resolve())
    else:
        # Default project root: a Ed.it Inbox folder under cwd so we don't
        # spray uploads into the user's working directory.
        default_root = Path.cwd() / "Ed.it Projects"
        default_root.mkdir(exist_ok=True)
        os.environ.setdefault("EDIT_PROJECT_ROOT", str(default_root))

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Add it to Ed.it/.env or your shell.", file=sys.stderr)
        return 2

    import uvicorn
    print(f"Ed.it serving on http://{args.host}:{args.port}  (root: {_project_root()})")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())

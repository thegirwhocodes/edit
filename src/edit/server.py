"""Web UI for Ed.it — FastAPI server wrapping the agent loop with SSE streaming.

Run:
    edit-web --root ~/Movies/MyProject
    # then open http://localhost:8765
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .agent import run_once


HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"


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
        full_brief = prompt
        if file:
            full_brief = f"The user uploaded `{file}` (relative to the project root). {prompt}"

        return StreamingResponse(_stream_agent(full_brief), media_type="text/event-stream")

    return app


async def _stream_agent(brief: str) -> AsyncIterator[str]:
    """Translate SDK message objects into typed SSE events for the UI."""
    yield _sse("brief", {"text": brief})
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
                        yield _sse("tool_result", {
                            "id": getattr(block, "tool_use_id", None),
                            "payload": payload,
                        })
            if kind == "ResultMessage":
                usage = getattr(msg, "usage", None)
                cost = getattr(msg, "total_cost_usd", None)
                summary = {"cost_usd": cost}
                if usage:
                    if isinstance(usage, dict):
                        summary["input_tokens"] = usage.get("input_tokens")
                        summary["output_tokens"] = usage.get("output_tokens")
                    else:
                        summary["input_tokens"] = getattr(usage, "input_tokens", None)
                        summary["output_tokens"] = getattr(usage, "output_tokens", None)
                yield _sse("done", summary)
    except Exception as e:
        yield _sse("error", {"message": str(e), "type": type(e).__name__})


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

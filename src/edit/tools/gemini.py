"""Gemini video understanding — the one tool that natively watches video.

We upload to the Files API, wait for processing, ask a question, then delete
the upload. Result is whatever structured text Gemini returns — the agent
parses it.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from claude_agent_sdk import tool

from ._safe import ToolError, ok, safe_path


def _content(payload: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


@tool(
    "describe_video",
    (
        "Watches a video file with Google Gemini and returns a natural-language "
        "description with timestamps. Use to find moments, scene changes, "
        "spoken content, or emotional peaks before deciding what to cut. "
        "Slow — uploads the file (10s–60s) and processes (10s–30s). Costs "
        "tokens. Returns Gemini's text answer."
    ),
    {
        "source_path": str,
        "question": str,
        "model": str,  # "gemini-2.5-flash" (default, cheap) | "gemini-2.5-pro"
    },
)
async def describe_video(args: dict[str, Any]) -> dict[str, Any]:
    try:
        src = safe_path(args["source_path"], must_exist=True, kind="video")
        question = args.get("question") or "Describe every scene change and notable moment with timestamps."
        model = args.get("model", "gemini-2.5-flash")

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ToolError(
                "missing_api_key",
                "GEMINI_API_KEY is not set.",
                "Add GEMINI_API_KEY to your environment or .env file.",
            )

        # Lazy import so this module loads even if google-generativeai is missing
        try:
            import google.generativeai as genai
        except ImportError:
            raise ToolError(
                "missing_dependency",
                "google-generativeai is not installed.",
                "Run: pip install google-generativeai",
            )

        genai.configure(api_key=api_key)

        # Upload + poll. Run blocking SDK calls in a thread to keep the loop free.
        def _upload_and_query() -> str:
            video_file = genai.upload_file(path=str(src))
            import time
            while video_file.state.name == "PROCESSING":
                time.sleep(2)
                video_file = genai.get_file(video_file.name)
            if video_file.state.name == "FAILED":
                raise ToolError(
                    "gemini_processing_failed",
                    f"Gemini failed to process {src.name}.",
                    "Try a shorter clip or a different container.",
                )
            try:
                gen_model = genai.GenerativeModel(model_name=model)
                resp = gen_model.generate_content(
                    [video_file, question],
                    request_options={"timeout": 600},
                )
                return resp.text
            finally:
                try:
                    genai.delete_file(video_file.name)
                except Exception:
                    pass

        text = await asyncio.to_thread(_upload_and_query)

        return _content(ok({
            "source_path": str(src),
            "model": model,
            "answer": text,
        }))
    except ToolError as e:
        return _content(e.to_payload())
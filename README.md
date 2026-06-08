# Ed.it

Desktop AI video editing agent. M1: CLI loop with a Claude Agent SDK brain and FFmpeg + Gemini tools.

## Quick start

```bash
cd "Social Media/Ed.it"
source .venv/bin/activate
pip install -e .

# Either drop a .env (see .env.example) or export the keys:
export ANTHROPIC_API_KEY=...
export GEMINI_API_KEY=...

# Sandbox the agent to a folder, then hand it a brief:
edit --root ~/clips "trim 0:05 to 0:15 of intro.mov into out/teaser.mp4"
```

## What's here (M1)

- Six tools wired through an in-process MCP server:
  - `probe_video` — ffprobe wrapper, structured metadata
  - `trim_clip` — stream-copy cuts with re-encode fallback
  - `concat_clips` — demuxer concat, requires matching codecs
  - `extract_audio` — WAV (16 kHz mono for Whisper) or M4A
  - `transcode` — h264/h265/prores normalization
  - `describe_video` — Gemini 2.5 Flash video understanding
- One sandboxed project root (`EDIT_PROJECT_ROOT`, defaults to cwd) — every path is resolved against it before any tool runs.
- Structured `ToolError` returns with `code` + `hint` so the agent recovers from failures instead of looping.
- Rich-formatted CLI with live tool-call narration and end-of-turn cost/usage line.

## Roadmap

| M | Goal |
|---|------|
| **M1** | naked agent loop + FFmpeg + Gemini, CLI only ← *here* |
| M2 | DaVinci Resolve MCP integration |
| M3 | Electron UI + streaming, Vercel AI SDK on the renderer |
| M4 | SQLite + sqlite-vec memory, `memory_recall` / `memory_write` tools |
| M5 | 3-variation render with subagent planners + Opus judge |
| M6 | prompt caching verified, Langfuse, $3 budget, signed installer |

See [docs/](docs/) for the full architecture research.

## Tests

```bash
pytest tests/
```

Each tool has happy + error path tests using a tiny generated `testsrc` clip — no external fixtures needed.
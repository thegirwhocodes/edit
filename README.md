# Ed.it

Desktop AI video editor. Drop a clip, type the brief, and let a local agent cut the video.

> Built on Claude Agent SDK + Gemini 2.5 Flash + FFmpeg, with a local SQLite
> memory layer and an Electron shell. Everything runs on your machine — only
> LLM calls leave it.

## Why it matters

Ed.it is the video-editing version of a real tool-using assistant: it can inspect media, call FFmpeg, ask Gemini what is happening in a clip, remember taste, track cost, and render variations. It is built like a local creative workstation, not a prompt wrapper.

## Quick start

### CLI
```bash
cd "Social Media/Ed.it"
source .venv/bin/activate
pip install -e .

# .env loads automatically; or export:
export ANTHROPIC_API_KEY=...
export GEMINI_API_KEY=...

edit --root ~/clips "trim 0:05 to 0:15 of intro.mov into out/teaser.mp4"
```

### Web
```bash
edit-web --root ~/Movies/MyProject
# open the URL it prints (default http://127.0.0.1:8765)
```

### Desktop (Electron)
```bash
cd electron
npm install
npm start          # dev mode
npm run build:mac  # produces a .dmg under electron/dist
```

The desktop shell auto-spawns the Python server on a free port, kills it on
quit, and stores projects under `~/Movies/Ed.it Projects/`.

## What's wired up

**Tools the agent can call**
- `probe_video` — ffprobe wrapper, structured metadata
- `trim_clip` — stream-copy cuts with re-encode fallback
- `concat_clips` — demuxer concat
- `extract_audio` — WAV (16 kHz mono for Whisper) or M4A
- `transcode` — h264/h265/prores normalization
- `describe_video` — Gemini 2.5 Flash video understanding
- `memory_recall` — keyword recall over SQLite + FTS5
- `memory_write` — log a durable fact about the user
- `preference_set` — record a scoped preference (worship / talking_head / lifestyle / global)
- `profile_write` — record an identity fact (always loaded into core memory)

**External MCP servers** — set `EDIT_USE_RESOLVE=1` to attach the DaVinci
Resolve MCP server at `~/Social Media/davinci-resolve-mcp/`.

**Memory** — one SQLite file (`memory.db`) per project root. FTS5 keyword
recall. Schema: `user_profile`, `preferences` (supersedes chain),
`projects`, `events`, `memory_items` (+ FTS5 mirror).

**Variations pattern** — the system prompt tells the agent to produce three
versions (Safe / Stretch / Wild) when the brief is open-ended, save them
to `out/v1.mp4`, `out/v2.mp4`, `out/v3.mp4`, and write a memory note for
whichever the user picks.

## Roadmap status

| M | Goal | State |
|---|------|-------|
| M1 | Naked agent loop + FFmpeg + Gemini, CLI only | ✅ shipped |
| M2 | DaVinci Resolve MCP integration | ✅ wired (opt-in via `EDIT_USE_RESOLVE`) |
| M3 | Electron desktop shell with streaming UI | ✅ shipped |
| M4 | SQLite memory + recall/write tools | ✅ shipped |
| M5 | 3-variation render pattern | ✅ prompt-level (rendering is the agent's job) |
| M6 | Cost tracking, traces DB, signing config | ✅ shipped |

### M6 details

**Cost & budget.** The agent SDK hard-stops at `EDIT_COST_BUDGET_USD` (default
$3) per session. The web layer adds a softer rolling-24h cap at
`EDIT_DAILY_BUDGET_USD` (default $5) — the UI pill turns amber at 75% and red
at 100%; new `/chat` calls return a `BudgetExceeded` SSE event when over cap.

**Traces.** Every chat turn is logged to `traces.db` under the project root:
brief, start/end times, cost, tokens, tool calls, output files, status
(`done`/`error`/`aborted`). The `/sessions?limit=N` endpoint returns
history; click the cost pill in the UI to see the last 20 runs.

**Prompt caching.** The system prompt is split into a stable head
(`STATIC_SYSTEM`) and a dynamic memory tail. As long as `memory_write`
stays rare (<1 per 10 turns, per the system-prompt policy), the head
cache-hits within Anthropic's 5-minute TTL — ~85% input-cost reduction
on the second turn within a session.

**Signing.** `electron/package.json` is wired to your existing Apple
Development cert (`naomiivie06@gmail.com / FL5RL9AY66`) with a hardened
runtime and `entitlements.mac.plist`. This signs for **personal use on
your machines**. To ship to other people, request a *Developer ID
Application* certificate from the Apple Developer portal and swap the
`identity` string. Notarization is a separate step (`xcrun notarytool`).

## Tests

```bash
pytest tests/ -q
```

13 tests cover the ffmpeg tools (happy + error paths) and the memory layer
(profile round-trip, preference supersedes, FTS recall, core block, all
four memory tools via the `@tool` decorators).

## Architecture

```
                  ┌──────────────┐
                  │  Electron    │  ←  main process spawns Python
                  │  shell (UI)  │      sub-process on free port
                  └──────┬───────┘
                         │ http://127.0.0.1:N
                         ▼
                  ┌──────────────┐
                  │  FastAPI     │  /upload  /chat (SSE)  /download
                  │  server.py   │
                  └──────┬───────┘
                         │
                  ┌──────▼───────┐       ┌────────────────┐
                  │  Claude      │ ───── │  edit-tools    │
                  │  Agent SDK   │       │  (in-process)  │
                  │  (Sonnet 4.5)│       └────────────────┘
                  └──────┬───────┘
                         │ optional
                         ▼
                  ┌──────────────┐
                  │ davinci-     │  (external MCP, stdio)
                  │ resolve MCP  │
                  └──────────────┘
```

See [docs/](docs/) for the architecture research that informed every choice.

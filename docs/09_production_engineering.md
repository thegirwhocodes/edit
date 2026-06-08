# 06 — Production Engineering for Ed.it

*Sibling docs: 01 frameworks, 02 agent loops, 03 tools/MCP, 04 multi-agent, 05 evaluation. This one is the "what do I do between the working prototype and real users" doc.*

You have an agent loop that works in a terminal. It calls Gemini for video understanding, Claude for planning, FFmpeg and DaVinci Resolve MCP for the actual edits. It kind of works. Now you need to ship it as a desktop app that doesn't cost $40 per session, doesn't leak API keys, doesn't hang on a spinner for 14 seconds, and doesn't silently fail when the user's laptop goes to sleep mid-render. This doc is opinionated. Where there are two paths, I pick one.

---

## 1. Prompt caching is the single biggest cost lever in 2026

If you do nothing else in this doc, do this. Prompt caching is a 5-10x cost cut on any agent with a stable system prompt and tool set, which is every agent. Ed.it's system prompt plus tool schemas plus few-shot examples is easily 8-15k tokens. Without caching you pay full price for all of them on every turn of a multi-turn conversation. With caching you pay ~10% of that on every turn after the first.

**Anthropic prompt caching.** You insert `cache_control: {"type": "ephemeral"}` breakpoints into your message blocks. Tokens *before* a breakpoint become cacheable. Cache lives 5 minutes by default (there is also a 1-hour beta tier at a higher write cost). Cache writes cost 1.25x base input; cache reads cost 0.1x base input. You can have up to 4 breakpoints per request. Order matters: put the most stable content first (system, tools, long few-shots), put the volatile user turn last and *outside* the cache.

**OpenAI automatic caching.** Automatic for prompts >1024 tokens on gpt-4o and newer. No `cache_control` param — the router hashes the prefix and caches it. You just have to keep your prefix byte-identical across calls (same system prompt, same order of tools). Caching is reported back in `usage.prompt_tokens_details.cached_tokens`. Same 50% discount on cached reads. Same practical advice: system + tools + examples *before* the user turn, don't shuffle them.

**Ed.it pattern.** Every agent turn carries (1) the Ed.it system prompt, (2) the full MCP tool catalog from Resolve + FFmpeg + Gemini File API, (3) 2-3 few-shot examples of "good edits," (4) the rolling conversation. (1)-(3) is stable across the session. (4) grows but the early turns also become stable once they're written. So you want two breakpoints: one after tools+examples, one after the last assistant turn. The user's new turn is outside any breakpoint.

```python
from anthropic import Anthropic

client = Anthropic()

SYSTEM = [
    {
        "type": "text",
        "text": ED_IT_SYSTEM_PROMPT,  # ~3k tokens
    },
    {
        "type": "text",
        "text": FEW_SHOT_EXAMPLES,     # ~5k tokens
        "cache_control": {"type": "ephemeral"},  # breakpoint 1
    },
]

resp = client.messages.create(
    model="claude-sonnet-4-5",
    system=SYSTEM,
    tools=RESOLVE_FFMPEG_GEMINI_TOOLS,  # tools are cached as part of the prefix automatically
    messages=[
        *prior_turns[:-1],
        {
            **prior_turns[-1],
            "content": [
                *prior_turns[-1]["content"],
            ],
            "cache_control": {"type": "ephemeral"},  # breakpoint 2: freeze everything up to here
        },
        {"role": "user", "content": new_user_message},  # outside cache
    ],
    max_tokens=4096,
)

print(resp.usage.cache_creation_input_tokens, resp.usage.cache_read_input_tokens)
```

In the Claude Agent SDK (`claude_agent_sdk` / `@anthropic-ai/claude-agent-sdk`) the cache breakpoints are set on the `system` blocks you pass to `query()` and on the last message of `options.resume_messages`. Instrument `cache_read_input_tokens / (cache_read_input_tokens + input_tokens)` as your cache hit rate. Target >80% on turns 2+ of a session.

The gotcha: any change to any byte before a breakpoint busts the cache. Don't interpolate the current timestamp into your system prompt. Don't reorder tools. Don't add a trailing newline. If your hit rate is 0%, diff the raw request payload across two consecutive turns.

---

## 2. Streaming UX — not optional

There is a perceived-latency cliff at about 3 seconds. Under 3s, users wait. Over 3s, users think the app froze. Agent turns with tool use routinely take 15-60s. Streaming is the only thing that keeps the UI feeling alive.

Stream four things:

1. **Text deltas** as the model generates them.
2. **Tool-call deltas** — the tool name as soon as it's chosen, then the arguments as they stream.
3. **Reasoning/thinking blocks** (Claude extended thinking, gpt-5 reasoning) — render these dimmed, collapsible.
4. **Status events** from *your* backend — "Gemini uploading 240MB clip," "FFmpeg 37% done," "Resolve timeline saved."

With the Anthropic SDK, `client.messages.stream(...)` yields events: `message_start`, `content_block_start` (with the block type: text / tool_use / thinking), `content_block_delta` (with `delta.type` = `text_delta` / `input_json_delta` / `thinking_delta`), `content_block_stop`, `message_delta` (usage), `message_stop`. Pipe these through to the renderer.

**Narrate-what-you're-doing pattern.** Before any tool runs, emit a one-line status event from the backend describing it in human terms. The model's tool call says `ffmpeg_trim(clip="b_roll_07.mov", start=12.4, end=18.1)`. The UI shows "Trimming B-roll clip 7 (5.7s)." Much better than a spinner. For Ed.it this is critical because edits take minutes and users need to know the agent is working, not stuck.

In an Electron app the cleanest plumbing is the Vercel AI SDK's data-stream protocol. On the renderer:

```tsx
import { useChat } from "ai/react";

const { messages, input, handleSubmit, status } = useChat({
  api: "/api/agent",
  onToolCall: ({ toolCall }) => {
    showStatus(`Running ${toolCall.toolName}…`);
  },
});
```

On the backend (Node/Electron main process, or Python via a thin HTTP shim), wrap the Anthropic stream and re-emit as AI SDK data-stream parts: `text`, `tool-call`, `tool-result`, `data` (custom), `finish`. If you're going Python-only, use `fastapi` + Server-Sent Events and your own lightweight event format — don't fight the SDK.

```python
async for event in stream:
    if event.type == "content_block_start" and event.content_block.type == "tool_use":
        yield sse("tool_call_start", {
            "id": event.content_block.id,
            "name": event.content_block.name,
            "narration": narrate(event.content_block.name),
        })
    elif event.type == "content_block_delta":
        if event.delta.type == "text_delta":
            yield sse("text", {"delta": event.delta.text})
        elif event.delta.type == "input_json_delta":
            yield sse("tool_args", {"id": ..., "partial": event.delta.partial_json})
```

First-token latency is what users feel. If your backend buffers even 500ms before flushing, streaming feels broken. Disable Nagle, disable proxy buffering, `flush=True`.

---

## 3. Structured outputs

Sometimes you need strict JSON: the edit plan that a downstream tool will parse, a classifier's label, a structured error report. Three approaches.

**(a) JSONSchema via the provider.** OpenAI's `response_format={"type": "json_schema", "json_schema": {...}, "strict": true}` — this is genuinely strict, the model cannot emit invalid JSON. Anthropic doesn't have a native structured-output endpoint, but coercing via tool use works: define one tool whose input_schema is your target schema, set `tool_choice={"type": "tool", "name": "emit_plan"}`, read the tool_use block's input. This is the standard pattern and it's reliable.

**(b) Grammar-constrained decoding.** For local models: llama.cpp's GBNF, xgrammar (the fastest as of late 2025, used in vLLM), Outlines, LM Format Enforcer. These constrain token sampling so only valid-JSON-per-your-schema tokens can be chosen. Useful if you ever run a local WhisperX-transcript-summarizer or a local LoRA-tuned classifier. Ed.it probably doesn't need this for the frontier model calls.

**(c) Pydantic validation + retry.** The "trust but verify" fallback. `instructor` (formerly `openai-function-call`) wraps the client to do exactly this: define a Pydantic model, call the LLM, validate, if it fails feed the validation error back with a retry prompt. Caps at 2-3 retries, then hard-fails.

**When each fails.** (a) fails silently when the schema is too permissive — you get valid JSON but semantically wrong. (b) fails when the grammar over-constrains and the model can't express what it needs, producing technically-valid-but-nonsense output. (c) fails when the model is wrong in a way Pydantic can't catch (wrong clip ID, hallucinated timestamp) — you need downstream validation against actual Resolve state.

For Ed.it: use (a) via tool_choice for every structured step. Add a second Pydantic validation pass for cross-field invariants (e.g. `end > start`, `clip_id exists in timeline`). Don't use grammar-constrained decoding on Claude or Gemini.

---

## 4. Cost control in production

An agent without a cost ceiling is a liability. Ed.it should enforce a **$3 per session hard ceiling** (configurable by the user, default $3). Track input, output, cache-read, cache-write tokens separately, multiply by current per-model rates, sum, abort with a graceful "I've hit this session's budget" when exceeded.

**Model routing.** Don't use one model for everything.

- **Haiku** (or gpt-5-nano) for classifiers: "is this clip a talking head or B-roll," "does this transcript mention a product?"
- **Sonnet** (or gpt-5) for workers: the main agent loop, tool-calling, planning.
- **Opus** (or gpt-5-pro) for rare hard planning: "produce the full edit plan for this 45-minute podcast." Invoke once per session, if at all.

Route at the call site, not via some config layer — makes it obvious in code what each call costs.

**Prompt compaction.** When the conversation history crosses ~100k tokens, compact it. Claude's `context_management.edits` with `strategy: "clear_tool_uses"` drops old tool result payloads (usually the bulk) while keeping the assistant's summaries. Or do it manually: after turn N, ask the model to produce a structured summary of the session so far, replace the first N turns with that summary, keep going. The Claude Agent SDK has this built in as `compact` — use it.

**Cache analytics.** Log `cache_read_input_tokens`, `cache_creation_input_tokens`, `input_tokens`, `output_tokens` per call to your metrics store. Compute hit rate per session. If hit rate drops below 60% investigate — someone probably changed the system prompt.

**UI cost display.** Show a running total in the Ed.it chat UI, e.g. "$0.47 / $3.00 this session." Users appreciate knowing. It also surfaces expensive agent behavior so you can fix it.

---

## 5. Observability stack

You need three things: **traces** (what happened, in order), **metrics** (aggregates over time), **logs** (raw prompts/responses for debugging a specific incident).

OpenTelemetry is the open standard. `opentelemetry-instrumentation-anthropic` and `opentelemetry-instrumentation-openai` auto-instrument SDK calls. `opentelemetry-instrumentation-bedrock`, `-gemini` exist too. For Ed.it, wire these on the Python backend and export OTLP.

Options for the backend:

- **Langfuse** — open-source, self-hostable, great prompt/trace UI, built for LLM traces specifically. My pick for Ed.it.
- **Braintrust** — hosted, strong eval tooling, good if you're already using their eval harness.
- **Logfire** (Pydantic) — great Python DX, nice for structured logs, less LLM-specific.
- **Arize Phoenix** — open-source, OTel-native.

A single trace for one agent turn should contain: the full input (system + messages + tools), every provider call with its latency and usage, every tool execution with args and result, the final response, total cost. You want to click one trace and see everything.

**Replay.** The killer feature. Given a trace, replay it against a new prompt or a new model. Langfuse, Braintrust, and Phoenix all support this. When a user reports "the edit was weird," you pull the trace, tweak the system prompt, replay, see if it's better. This is how you iterate on prompts without re-recording video test cases every time.

Log sampling: 100% of errored turns, 100% of turns flagged by the user (thumbs-down in the UI), 10% of successful turns. Never log video frames — transcript and metadata only.

---

## 6. Secrets and API keys

Ed.it runs on the user's Mac. The API keys sit on the user's machine. Three options.

**(a) BYO keys in OS keychain.** User pastes their Anthropic + Gemini keys into Ed.it settings. Ed.it stores them via `keyring` (Python) → macOS Keychain → Windows Credential Manager → libsecret on Linux. Electron: `keytar` or `safeStorage` (the latter is built-in and backed by Keychain/DPAPI). Keys never touch disk in plaintext, never touch your servers.

**(b) Proxy through your server.** You hold the key, you charge the user, they never see a key. Adds infra, adds latency (every token round-trips through you), adds liability for you. Eventually the right answer for a polished consumer product.

**(c) Per-user issued keys.** You provision a scoped key per user through your account system. Rare, usually only for enterprise.

**For Ed.it MVP: (a).** Naomi is a developer, the early users will be developers, they have API keys. Use `keytar` in Electron's main process. Never pass the key to the renderer; the renderer sends chat requests to the main process, the main process calls Anthropic/Gemini. If you ever add a Python subprocess, pass the key via an env var set at spawn time, never via command-line args (visible in `ps`).

Migrate to (b) later when you have non-developer users.

---

## 7. Packaging an agent into a desktop app

Two realistic paths.

**(A) Electron + bundled Python backend.** Electron shell hosts the UI. A Python process (frozen with PyInstaller or Nuitka) runs the agent, FFmpeg orchestration, WhisperX, PIL, and the Resolve MCP client. Electron spawns it as a subprocess, talks over stdio JSON-RPC or local HTTP on 127.0.0.1:<random>. Pros: you get Python's ML ecosystem (PyTorch for WhisperX, transformers, etc.). Cons: bundle size (200-800MB with torch), PyInstaller quirks, codesigning a Python binary is finicky.

**(B) TypeScript-only with `@anthropic-ai/claude-agent-sdk`.** Everything in Node. Pros: one language, one bundle, simpler packaging, smaller installer. Cons: no PyTorch — you'd call WhisperX as a CLI subprocess anyway, or use a hosted transcription API. PIL-equivalent image ops are fine (sharp, jimp). But WhisperX needs Python in practice.

**Recommendation for Ed.it: (A).** You need WhisperX (PyTorch), you want PIL for thumbnail composition, and the DaVinci Resolve MCP server is Python. Bundling Python is annoying but unavoidable. Structure:

```
Ed.it.app/
  Contents/
    MacOS/Ed.it                 # Electron launcher
    Resources/
      app.asar                  # JS/TS renderer + main
      python/                   # PyInstaller --onedir frozen backend
        ed_it_backend           # entrypoint binary
        _internal/              # libs
      ffmpeg                    # static ffmpeg binary
```

Main process spawns `python/ed_it_backend --port 0`, reads the chosen port from stdout, talks to it over HTTP. Backend exits when main disconnects. Use `electron-builder` with `extraResources` to bundle the python dir and ffmpeg.

---

## 8. Updates, signing, release

**macOS.** Apple Developer ID certificate ($99/yr). Sign every binary in the bundle including the Python interpreter and every `.so` inside `_internal/`. Then notarize via `xcrun notarytool submit --wait`. Then staple. Then and only then will Gatekeeper not scare your users. `electron-builder` handles most of this with the right `build.mac` config; the Python stuff you sign separately before electron-builder packages it.

**Windows.** Authenticode certificate (EV preferred, ~$300/yr and an HSM requirement, but instant SmartScreen reputation). Sign the .exe and the Python .exe inside. `electron-builder` handles it.

**Auto-updates.** `electron-updater` with a GitHub Releases or S3 feed. Differential updates via blockmap to keep download sizes small. The Electron shell updates by downloading a new full app.

**Python backend updates.** Two choices: (1) bundle Python with every Electron release — simple, but every Python change ships a 300MB update; (2) version the Python backend separately, download it on first launch and on version mismatch, cache in `app.getPath("userData")/backend/<version>/`. (2) is more engineering but way better UX. For MVP start with (1). Move to (2) when updates get painful.

Release cadence: weekly canary, monthly stable. Keep a kill-switch — a config endpoint you can hit to force all clients to stop making LLM calls if a prompt injection gets discovered.

---

## 9. Local-first data and sync

SQLite is the source of truth for project data, chat history, edit plans, asset catalogs, cost ledger. Use `better-sqlite3` from Electron main (synchronous, fast) or `aiosqlite` from Python (async).

Schema lives in one file, migrations via `@squeakyfeet/drizzle-kit` or raw `ALTER` scripts versioned with a `schema_version` table. Don't use an ORM for anything complex — raw SQL is clearer and survives better.

**Cloud sync: only when needed.** Don't build sync for v1. It's a huge amount of work (conflict resolution, CRDTs, auth). Ed.it is a single-user desktop app. Add sync when someone actually wants it across their laptop and studio Mac. When you do, look at Turso's libSQL embedded replicas or a rolled solution with a server-side `updated_at` last-writer-wins for non-conflicting tables.

**Encryption at rest.** SQLCipher if you're storing API keys, transcripts of private recordings, or anything the user would be upset about. Key derived from a user passphrase or the OS keychain. For Ed.it MVP: Keychain holds API keys, project DB is plaintext SQLite but in the sandboxed app container. Revisit if you add cloud sync.

**Export/import.** From day one, a "Export Project" button that writes a `.eddit` zip: SQLite db + referenced media manifests (not the media itself, just paths + hashes). Users trust apps that let them leave.

---

## 10. Performance

**First-token latency target: <1s ideal, <3s acceptable.** Measure TTFT end-to-end (user press enter → first token on screen). Most of this is provider latency; you control the rest — don't add needless proxy hops, pre-warm the provider SDK client at app start.

**Throughput.** Frontier models output 50-100 tokens/sec. At 100 t/s a 1000-token response takes 10 seconds — streaming makes this bearable. The LLM is the bottleneck except when:

- **FFmpeg renders** (minutes to hours) — stream `-progress pipe:1` output, parse `out_time_us`, emit progress events to the UI every 500ms.
- **Gemini File API upload** (tens of seconds for large videos) — chunked upload with progress.
- **WhisperX transcription** (minutes for long videos) — progress callback from the model.

**Concurrency.** One agent session per UI window. A separate background daemon for the file watcher (watches the user's Movies folder, triggers thumbnail generation, transcript caching). Daemon has its own tiny agent or, better, no agent at all — deterministic pipeline.

**Rate limits.** Anthropic has tier limits (tier 1: 50 RPM, 40k ITPM on Sonnet; higher tiers are higher). Gemini free tier is very restrictive (15 RPM on flash); paid is generous. Handle 429s with exponential backoff with jitter. Respect `retry-after` headers. Surface "You're hitting your provider's rate limit, waiting 8s…" in the UI rather than silently stalling.

---

## 11. Privacy and data handling

Draft for the Ed.it privacy one-pager:

> **What leaves your machine.**
>
> - **Video frames** go to Google's Gemini File API when the agent needs to understand visual content. Files are deleted automatically after 48 hours, or manually by Ed.it when the edit session ends. Gemini's terms prohibit training on your data by default on paid tiers; Ed.it uses paid tier.
> - **Transcripts and edit metadata** (clip names, timestamps, your chat messages) go to Anthropic's Claude API. Anthropic does not train on API data. Ed.it opts into zero-data-retention where your account permits it.
> - **Nothing leaves for local operations.** FFmpeg renders, WhisperX transcription, thumbnail generation, DaVinci Resolve control — all 100% on your machine.
> - **Your API keys** are stored in your operating system's keychain (macOS Keychain / Windows Credential Manager). Ed.it cannot see them outside of the moment it makes an API call.
> - **Your project files** — the SQLite database, your chat history, your edit plans — never leave your machine unless you explicitly export them.

Put this in the app, in settings, plain English. Don't bury it in a 40-page EULA.

---

## 12. Day-1-of-shipping checklist for Ed.it

- [ ] Prompt caching enabled with `cache_control` breakpoints on the Anthropic SDK call path; cache hit rate instrumented and visible in a debug overlay.
- [ ] Streaming end-to-end: text, tool calls, status narration. No spinner lives for more than 2 seconds.
- [ ] Per-session $3 cost ceiling enforced; live cost display in the chat UI; model routing (Haiku/Sonnet/Opus) deliberate per call site.
- [ ] Langfuse (or equivalent) wired via OpenTelemetry; every turn produces a trace with inputs, tool calls, usage, and replay capability.
- [ ] API keys stored via Electron `safeStorage` / `keytar`; keys never touch the renderer process, never touch disk in plaintext, never in command-line args.
- [ ] Electron app bundles a PyInstaller-frozen Python backend plus static FFmpeg; spawned over localhost HTTP with a random port.
- [ ] macOS: Developer ID signed, notarized, stapled. Windows: Authenticode signed. Auto-updates via `electron-updater` pointed at GitHub Releases.
- [ ] SQLite schema versioned with migrations; Export Project button produces a portable `.eddit` file from day one.
- [ ] FFmpeg and WhisperX emit progress events streamed to the UI; rate-limit 429s handled with backoff and user-visible messaging.
- [ ] Privacy one-pager written and shipped inside the app settings, describing exactly what data goes where.

---

*This document was written drawing on training knowledge through January 2026. Provider APIs, SDK versions, and pricing move fast — verify current `cache_control` syntax, rate-limit tiers, and notarization requirements against the live docs at ship time. URLs intentionally omitted to avoid citing stale links.*

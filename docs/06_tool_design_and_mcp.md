# 03 — Tool Design and MCP

*Sibling docs: [01 Agent Frameworks](./01_agent_frameworks.md), [02 Agent Loops](./02_agent_loops.md). This doc is the tool surface.*

An agent is only as good as the tools you hand it. The loop is plumbing; the tools are the actual capability surface. For Ed.it — a creator-facing desktop agent that edits video through Gemini, FFmpeg, and DaVinci Resolve MCP — tool design *is* the product. Get it wrong and the agent will pick the wrong FFmpeg filter, blow away a Resolve project, or hallucinate a clip name that doesn't exist. Get it right and it feels like a real editor sitting at your workstation.

This doc is opinionated. Where two patterns conflict I pick one.

---

## 1. What a "tool" actually is in 2026

Forget the OpenAI API surface for a second. A tool, operationally, is three things:

1. **A function** — Python, TS, a shell script, whatever. It executes and returns a value.
2. **A JSONSchema** — describes the input params: names, types, enums, required/optional, descriptions.
3. **A description** — a docstring-grade natural-language blurb explaining *when to call this tool and what it does for the user*.

The critical, load-bearing thing nobody tells you: **the model picks tools based almost entirely on the description and parameter names, not the code behind it.** The LLM never sees your implementation. It sees a name, a one-paragraph description, and a schema. That is the entire surface area it reasons over.

This flips the authoring workflow. You are not writing a Python function and tacking metadata on; you are writing a micro-spec for an LLM reader whose implementation happens to also run.

Rules that follow from this:

- **Name tools like verbs + objects.** `trim_clip`, `extract_audio`, `list_timeline_markers`. Not `handler`, not `util_1`, not `do_resolve_thing`.
- **Descriptions answer "when should I call this?"** Not "what does this do internally?" Bad: *"Runs ffmpeg -i with -ss and -t flags."* Good: *"Cuts a clip from a source video between two timestamps. Use when the user asks to trim, shorten, or extract a segment. Returns the path to the new clip."*
- **Params are first-class UX.** Every param gets its own description. Enums for anything with a known value set. Don't use free-form strings where `"h264" | "h265" | "prores"` would do.
- **Returns are structured JSON, never prose.** The agent needs to pattern-match on `status`, `path`, `duration_sec`, not parse a sentence you wrote.

---

## 2. Schema design: good tool vs. bad tool

A concrete rewrite, both for Ed.it's trim operation.

### Bad

```json
{
  "name": "ffmpeg_run",
  "description": "Runs an ffmpeg command.",
  "parameters": {
    "type": "object",
    "properties": {
      "args": { "type": "string", "description": "Command line args" }
    },
    "required": ["args"]
  }
}
```

Problems: zero semantics. The model has to synthesize an ffmpeg invocation from scratch, which it will do wrong 20% of the time. No enum constraints. No structured return. The tool is just a shell — you've outsourced all the hard reasoning to the LLM and kept none of the engineering.

### Good

```json
{
  "name": "trim_clip",
  "description": "Cuts a segment from a source video file between two timestamps and writes a new file. Use this when the user wants to shorten a clip, extract a highlight, or isolate a moment. Does not re-encode when possible (stream copy). Returns the output path and actual duration.",
  "parameters": {
    "type": "object",
    "properties": {
      "source_path": {
        "type": "string",
        "description": "Absolute path to the input video file."
      },
      "start_sec": {
        "type": "number",
        "description": "Start time in seconds, measured from the beginning of the source."
      },
      "end_sec": {
        "type": "number",
        "description": "End time in seconds. Must be greater than start_sec."
      },
      "output_dir": {
        "type": "string",
        "description": "Directory to write the trimmed clip into. Must exist."
      },
      "reencode": {
        "type": "string",
        "enum": ["never", "if_needed", "always"],
        "description": "Stream-copy by default. 'if_needed' re-encodes only on keyframe misalignment.",
        "default": "if_needed"
      }
    },
    "required": ["source_path", "start_sec", "end_sec", "output_dir"]
  }
}
```

And the return:

```json
{
  "status": "ok",
  "output_path": "/Users/naomi/proj/clips/shot_03_trim.mp4",
  "duration_sec": 4.21,
  "reencoded": false
}
```

Rules to internalize:

- **Single responsibility per tool.** `trim_clip` trims. `concat_clips` concats. Don't build a `video_op` god-tool.
- **Flat params over nested.** JSONSchema supports nested objects; the model handles them worse than flat. If you have `{ output: { dir, filename } }`, collapse to `output_dir` and `output_filename`.
- **Enums everywhere you can.** `codec`, `container`, `resolution_preset`, `aspect_ratio`. The model is much more accurate picking from a list than typing a string.
- **Required is a contract.** Mark everything required unless it genuinely has a sane default.
- **Return shape is stable.** Always include a `status` field. Always include enough context for the next step (the output path, not just "success").

---

## 3. The MCP ecosystem in 2026

MCP — Model Context Protocol — is Anthropic's open protocol, announced late 2024, for exposing tools, resources, and prompts to LLM clients. By early 2026 it has become the dominant interop layer for agent tooling. It is not a framework; it is a wire protocol.

**What it defines:**

- **Tools** — callable functions (what this doc is mostly about).
- **Resources** — read-only content the server can expose (files, URLs, database rows). The client can list and fetch them; the model can be given them as context.
- **Prompts** — parameterized prompt templates the server offers to the client. Think of them as server-provided slash commands.

**Transports that matter:**

- **stdio** — local subprocess, the default for desktop. The MCP server is a child process, JSON-RPC over stdin/stdout. This is what Ed.it will mostly use.
- **Streamable HTTP** — the 2025 replacement for the earlier SSE transport. Single HTTP endpoint, supports bidirectional streaming. Used for remote MCP servers (hosted SaaS tool providers).
- **SSE** is still supported by some clients for backwards compat but is deprecated in the spec.

**Clients that ship MCP support as of early 2026:**

- Claude Desktop, Claude Code, Claude Agent SDK
- OpenAI Agents SDK (added MCP client support in 2025)
- Cursor, Windsurf, Zed
- Gemini CLI / Gemini Code Assist
- GitHub Copilot (Agent mode)
- Various IDE plugins and the `mcp-cli` reference client

**Dynamic discovery.** Every MCP server responds to `tools/list`, `resources/list`, `prompts/list` at runtime. This means your client doesn't need to hardcode the tool list — it asks the server what's available each session. Ed.it should use this: the Resolve MCP server may expose new tools across versions, and we don't want to recompile to pick them up.

**Servers worth knowing:**

- `modelcontextprotocol/servers` — the reference repo, includes filesystem, git, fetch, sqlite, time, memory, etc.
- `samuelgursky/davinci-resolve-mcp` — the one Ed.it uses for Resolve control.
- `@cloudflare/mcp-server-cloudflare` — canonical remote MCP example.
- GitHub's official `github-mcp-server`.
- Dozens of community servers for Slack, Notion, Linear, Postgres, etc.

---

## 4. Build vs. wrap vs. use existing MCP

Decision matrix:

| Situation                                                | Pick                       |
| -------------------------------------------------------- | -------------------------- |
| Well-known external app with a live MCP server           | Use the MCP server         |
| Internal CLI or binary (FFmpeg, your own scripts)        | Write a custom tool        |
| SDK call to a well-behaved API (Gemini Files, OpenAI)    | Direct SDK call in a tool  |
| You'll use it from multiple agents/clients               | Wrap as an MCP server      |
| One-shot, one-agent, one-process                         | Inline tool, skip MCP      |

For Ed.it specifically:

- **FFmpeg** → custom tools. Don't give the agent a raw `ffmpeg_run` (see section 2). Instead build a curated set: `trim_clip`, `concat_clips`, `extract_audio`, `apply_lut`, `generate_thumbnail`, `transcode`. Each wraps a specific FFmpeg invocation you've tested. Roughly 10–15 tools total covers 95% of Ed.it's needs.
- **DaVinci Resolve** → use `samuelgursky/davinci-resolve-mcp`. It already exposes project/timeline/clip operations through Resolve's Python API. Don't reimplement.
- **Gemini Files API** → direct SDK call inside a custom tool. There is no Gemini MCP server worth wrapping around; the SDK is clean. Expose two or three tools: `upload_video_to_gemini`, `describe_video`, `find_moments`. The MCP layer would add latency and give you nothing.
- **Filesystem** → use the reference `filesystem` MCP server, scoped to the user's project directory. Don't roll your own.

Rule of thumb: **MCP when the tool surface is reusable or cross-process; custom inline when it's specific to this agent.**

---

## 5. Writing an MCP server end-to-end

Here is a minimal TypeScript MCP server exposing one tool — roughly 30 lines with `@modelcontextprotocol/sdk`. This is the shape; production servers add more tools, resources, and error handling.

```ts
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const run = promisify(execFile);
const server = new Server({ name: "edit-ffmpeg", version: "0.1.0" }, {
  capabilities: { tools: {} },
});

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [{
    name: "probe_video",
    description: "Returns duration, resolution, fps, and codec of a video file. Use to inspect a clip before editing.",
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string", description: "Absolute path to the video file." },
      },
      required: ["path"],
    },
  }],
}));

server.setRequestHandler(CallToolRequestSchema, async (req) => {
  if (req.params.name !== "probe_video") {
    return { content: [{ type: "text", text: JSON.stringify({ status: "error", message: `Unknown tool ${req.params.name}` }) }], isError: true };
  }
  const { path } = req.params.arguments as { path: string };
  try {
    const { stdout } = await run("ffprobe", ["-v", "error", "-print_format", "json", "-show_streams", "-show_format", path]);
    return { content: [{ type: "text", text: stdout }] };
  } catch (e: any) {
    return { content: [{ type: "text", text: JSON.stringify({ status: "error", message: e.message, hint: "Check that the path exists and ffprobe is installed." }) }], isError: true };
  }
});

await server.connect(new StdioServerTransport());
```

The Python SDK (`mcp` package, `pip install mcp`) is equivalent — same concepts, `@server.list_tools()` and `@server.call_tool()` decorators. Pick based on where the rest of your code lives. Ed.it's backend is Python, so Python SDK for any Ed.it-authored servers.

A few things worth noting from the snippet:

- `inputSchema` is the *tool author's* JSONSchema. MCP passes it to the client verbatim.
- `content` is an array of content blocks. Text is most common; images and resources are also supported.
- `isError: true` marks tool-level errors distinct from protocol errors. Clients surface this to the model.

---

## 6. Error handling for agents

The core insight, which separates tools that work from tools that don't:

> **The model recovers better from a helpful error message than from a stack trace.**

When your tool fails, you are writing a prompt to the agent about what to do next. Treat it that way.

Bad:

```
TypeError: Cannot read properties of undefined (reading 'duration')
    at probeVideo (/app/src/ffmpeg.ts:42:18)
    at async Object.handler
    ...
```

The agent reads this, sees "TypeError," has no idea if the file was missing or the binary crashed, and will likely retry the same call.

Good:

```json
{
  "status": "error",
  "code": "file_not_found",
  "message": "Source file does not exist at /Users/naomi/clips/shot99.mp4.",
  "hint": "List the project directory with list_media_files before referencing a clip. The user may have renamed or moved it."
}
```

The agent now knows (a) it was a missing file, (b) what to try next. It will call `list_media_files`, find `shot99_v2.mp4`, and retry with the correct path.

Standard shape I use:

```json
{
  "status": "error" | "ok",
  "code": "short_snake_case_code",
  "message": "human-readable description",
  "hint": "next-step suggestion for the agent"
}
```

Three classes of errors to handle explicitly:

1. **User-input errors** (bad path, invalid timestamp). Surface the bad value, suggest a validator tool.
2. **Precondition errors** (Resolve isn't running, Gemini API key missing). Surface the precondition; don't let the agent retry.
3. **Transient errors** (network, rate limit). Mark `code: "transient"` so the agent retries with backoff.

---

## 7. Approval and permissioning

Ed.it is a desktop app that runs shell commands, touches the filesystem, and talks to Resolve. The threat model is real:

- An FFmpeg tool with a malformed filter chain could corrupt media or, if we're sloppy with path handling, `rm -rf` something.
- A Resolve tool could overwrite the user's project bin or delete a timeline.
- The Gemini Files API will happily upload whatever path you give it.

Patterns:

- **Tag dangerous tools.** In tool metadata, mark `destructive: true` on anything that writes, deletes, or mutates user state. Non-destructive tools (probe, list, describe) can auto-approve. Destructive ones prompt.
- **Use approval hooks.** The Claude Agent SDK exposes `canUseTool(toolName, args) => "allow" | "deny" | "ask_user"`. Ed.it's implementation:
  - `probe_*`, `list_*`, `describe_*` → allow.
  - `trim_clip`, `concat_clips`, `transcode` → allow if output path is inside the project dir; ask otherwise.
  - `delete_clip`, `overwrite_project`, anything Resolve-mutating → ask every time for the first few sessions, then let the user toggle "trust this tool."
- **Sandbox paths.** The FFmpeg tool wrapper should resolve input/output paths against an allowlist (project root). Reject `../` traversal. Reject absolute paths outside the project unless explicitly allowed.
- **No `shell=True`.** Use `execFile` / `subprocess.run([...])` with argument lists. The model will sometimes try to inject shell metacharacters into a filename field; arg-list exec neutralizes it.
- **Dry-run mode.** Every destructive tool takes an optional `dry_run: bool`. The agent can call with `dry_run=true` first to preview what would happen, surface it to the user, then re-call without it.

---

## 8. Dynamic tool sets

Here's a finding worth hammering: **tool selection accuracy degrades past roughly 20–30 tools in the active set.** The model starts confusing similar tools, picks lower-ranked ones more often, and latency goes up because every tool description is in the prompt.

Ed.it, fully loaded, will have 40+ tools across FFmpeg, Resolve, Gemini, filesystem, and project-management layers. You cannot hand the agent all 40 every turn.

Two patterns:

### Per-step active tools (Vercel AI SDK pattern)

The AI SDK exposes `activeTools: string[]` on every `generateText` call. Filter the tool set based on the current phase or last tool call. Ed.it's phases:

- **Analyze phase** — Gemini tools, probe tools, list tools. No writes.
- **Plan phase** — read-only Resolve tools, markers, timeline inspection.
- **Render phase** — FFmpeg tools, Resolve export.
- **Polish phase** — color, audio, subtitles.

Each phase exposes 8–12 tools max. Transitions happen via a `handoff` tool or an explicit planner decision.

### Per-subagent tool partitioning

Alternative: instead of phases on one agent, spawn specialized subagents (a pattern covered in detail in doc 02). Each subagent gets a narrow tool set:

- `MediaAnalyst` → Gemini + probe tools.
- `TimelineEditor` → Resolve MCP tools.
- `Renderer` → FFmpeg + Resolve export.

The parent orchestrator has only `delegate_to_<agent>` tools — maybe 4 or 5 total. Each subagent sees only its own tools. This scales much better and is the pattern Ed.it should use.

Claude Agent SDK supports this directly via `agents:` config; the OpenAI Agents SDK via `Agent.as_tool()`; LangGraph via subgraph composition.

---

## 9. Testing tools

A tool has three testable surfaces; write tests for all three.

**Unit tests on the function.** Standard stuff. `trim_clip` with a known input produces a file of the expected duration. Mock `subprocess` if you want speed; run against real FFmpeg in integration.

**Contract tests on the schema.** The JSONSchema must match the function signature. A Python helper like `pydantic`-derived schemas gives you this for free. In TS, use `zod` with `zod-to-json-schema`. Every PR that changes the function without updating the schema should fail CI.

**Golden-path evals on tool selection.** This is the one most people skip and is the most valuable. Given a prompt like *"trim the first 5 seconds off clip3.mp4"*, does the agent call `trim_clip` with `start_sec=5`? Build a suite of 50–100 such prompts, run them against the tool-decision step (not the full loop), and assert the chosen tool and arguments match expectations. Cheap — only uses one LLM call per eval — and catches regressions when you rename a tool or tweak a description.

**Synthetic error injection.** For each tool, simulate each error class (file not found, subprocess exit 1, timeout, malformed output) and verify the agent's next action is sensible. This is how you validate your error messages from section 6 actually work.

Run all four suites in CI. The golden-path evals will cost a few dollars per run; worth it.

---

## 10. Observability

From day one, every tool call logs:

- `tool_name`
- `arguments` (redacted if sensitive)
- `started_at`, `duration_ms`
- `status` (`ok` | `error`)
- `error_code` if any
- `agent_id` / `session_id` / `turn_id`
- `cost_usd` for tools that hit paid APIs (Gemini)

Structured, JSON, one line per call. Ship to a local SQLite during dev, to OpenTelemetry + a backend (Honeycomb, Phoenix, Langfuse) in staging/prod. OpenInference and Langfuse both have semantic conventions for LLM/agent spans — use them; don't invent your own.

Why this matters from day one:

- **Debugging.** When the agent does something dumb, the first question is always "what tools did it call and with what args?" Logs answer that instantly.
- **Cost tracking.** Gemini video analysis isn't free. Per-session cost dashboards from week one.
- **Selection accuracy.** Aggregate which tools get picked, which ones always fail, which ones the agent retries. This is the feedback loop for improving descriptions.
- **User replay.** When a user says "it messed up my project," you can replay the exact tool sequence.

Traces in, traces out. If you have to choose one piece of agent infrastructure to build before launch, it is this, not fancy orchestration.

---

## Knowledge cutoff

This doc draws on training knowledge through January 2026. MCP spec, SDK APIs, and named servers (`samuelgursky/davinci-resolve-mcp`, `modelcontextprotocol/servers`, `@cloudflare/mcp-server-cloudflare`) are cited from what I am confident exists as of that cutoff. Specific version numbers, endpoint URLs, and recent API changes should be verified against live docs before implementation. Web access was not available during authoring.

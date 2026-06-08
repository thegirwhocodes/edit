# Research 1 — AI Agent Framework Comparison (2026)

For a desktop AI video editing agent ("Ed.it"). Written Jan 2026.

## 1. Claude Agent SDK (Anthropic)

**Core architecture.** Renamed from "Claude Code SDK" in Sep 2025. Exposes the same harness Claude Code runs on: main agent loop with tool use, optional subagents, filesystem as context, persistent memory (`CLAUDE.md` + `/memory`), hooks (PreToolUse, PostToolUse, SessionStart, Stop, SubagentStop, UserPromptSubmit), slash commands, first-class MCP client support. Tools declared as JSONSchema or imported from MCP servers. SDK manages tool-call loops, partial JSON streaming, interrupts. TypeScript (`@anthropic-ai/claude-agent-sdk`) and Python (`claude-agent-sdk`).

**Memory/state.** Three layers: (1) conversation, (2) automatic `CLAUDE.md` on session start, (3) explicit `/memory` file edits by the agent. Session transcripts persist to disk — resumable via `--resume <session_id>`. Context editing + 1M context on Sonnet 4.5 / Opus 4.7 means long-running sessions don't need a hand-rolled vector DB for working memory.

**Streaming.** Native SSE streaming of text + tool use blocks. `query()` async iterator yields `AssistantMessage`, `ToolUseBlock`, `ToolResultBlock`, `ThinkingBlock` — easy to pipe into a UI.

**Best fit.** Anything where the agent needs filesystem access, long-horizon planning, subagent delegation, or tool orchestration. Unmatched for "agent that operates on a user's machine."

**Gotchas.** Opinionated — you inherit Claude Code's system prompt conventions unless you override `systemPrompt: { type: "custom" }`. MCP server lifecycle is your problem (spawn/kill). Subagents don't share memory with the parent by default. Cost: Sonnet 4.5 ~$3/$15 per MTok with prompt caching is cheap enough for a local app; Opus is 5x.

**Docs.** docs.claude.com/en/api/agent-sdk/overview · GitHub: `anthropics/claude-agent-sdk-typescript`, `anthropics/claude-agent-sdk-python`.

## 2. OpenAI Agents SDK

**Core architecture.** Released March 2025 as successor to Swarm. Primitives: `Agent` (LLM + instructions + tools), `Handoff` (agent-to-agent transfer as tool call), `Guardrail` (input/output validators, run in parallel), `Runner` (loop). MCP support since mid-2025. Built-in tracing dashboard at platform.openai.com.

**Memory/state.** Thinner than Claude's. Conversation state is a list passed to `Runner.run()`; persist it yourself. OpenAI's Responses API has server-side `previous_response_id` chain — not durable long-term memory.

**Streaming.** `Runner.run_streamed()` — emits `RawResponsesStreamEvent`, `RunItemStreamEvent`.

**Best fit.** Multi-agent workflows where handoffs are the natural abstraction (customer service → specialist, triage → worker). Great if you're GPT-5 / o4-locked.

**Gotchas.** Weaker filesystem/coding primitives than Claude SDK — no "here's a checkout of files, go edit them." No hooks equivalent. Less mature MCP tooling. Tracing is proprietary.

**Docs.** openai.github.io/openai-agents-python/

## 3. LangGraph

**Core architecture.** Graph executor where nodes are functions (usually LLM calls) and edges are conditional transitions. Define a `StateGraph` with typed state dict; nodes mutate state. Cycles, subgraphs, parallel branches.

**Memory/state.** Best-in-class. `Checkpointer` (SQLite/Postgres/Redis) snapshots at every step — time travel, replay, human-in-the-loop interrupts via `interrupt()` free. `Store` API for long-term cross-thread memory with namespaces.

**Streaming.** Token, node-event, state streams via `graph.astream()` with `stream_mode`.

**Best fit.** Complex, branchy pipelines with explicit control flow — "analyze video → if score<0.7 retry with different prompt → else render → HITL review." Three-variations-and-pick-best maps directly to a LangGraph cycle.

**Gotchas.** Verbose. Lots of node/edge code for things Claude SDK gives you free. Not tied to any model provider (pro and con). Steepest learning curve on this list.

**Docs.** langchain-ai.github.io/langgraph/

## 4. Vercel AI SDK

**Core architecture.** Not really an agent framework — universal LLM client + React/Svelte/Vue hooks. v5 (Aug 2025) introduced `Agent` class with `stopWhen` loop conditions, typed tool calls, agentic primitives (`prepareStep`, `activeTools`). `streamText`, `generateText`, `streamUI` core primitives. `useChat` hook handles message state on the client with full SSE streaming of tool calls, reasoning, data parts.

**Memory/state.** BYO — stateless on the server; client holds message history. Pairs with any backend memory layer.

**Streaming.** Unbeatable for UI. Multi-step tool calls stream incrementally; client sees `tool-call-streaming-start`, argument deltas, results, all as they happen. Works in React Server Components.

**Best fit.** The UI layer of an Electron app. Do NOT use as the brain.

**Gotchas.** "Agent" abstraction is lightweight — no subagents, no checkpointing, no hooks. If you need orchestration, use alongside something else.

**Docs.** ai-sdk.dev

## 5. CrewAI / AutoGen / LlamaIndex Agents

Short answer: **largely superseded for this use case.**

- **CrewAI** — alive but niche for "role-playing crew" demos. Agent/Task/Crew YAML abstraction is brittle for filesystem-heavy work. Skip.
- **AutoGen** — Microsoft rewrote as `autogen-core` + `autogen-agentchat` late 2024; part of the Magentic-One / Semantic Kernel orbit. Decent for research; in 2026 most production teams moved to LangGraph or OpenAI Agents SDK.
- **LlamaIndex Agents** — LlamaIndex still the RAG leader. Agent layer (`AgentWorkflow`) usable but niche — for "agent over a giant document corpus." Not our problem.

## 6. MCP (Model Context Protocol)

**Status in 2026.** De-facto tool-interop standard. Anthropic, OpenAI, Google (Gemini), Microsoft Copilot, Cursor all ship MCP clients. Servers expose `tools`, `resources`, `prompts`, and (since late 2025) `sampling` + `elicitation`. Transport: stdio (local) and streamable HTTP (remote, replaced SSE).

**Dynamic discovery.** Yes. Clients connect to servers at runtime, call `tools/list`, expose tools to the agent. Claude Agent SDK, OpenAI Agents SDK, LangGraph (via `langchain-mcp-adapters`), Vercel AI SDK all support dynamic MCP connections.

**For the existing DaVinci Resolve MCP.** All four frameworks can connect. Claude Agent SDK has the cleanest story — drop the server into `mcpServers` in SDK options and its tools are auto-exposed.

## 7. Recommended Stack for Ed.it

**Brain: Claude Agent SDK (TypeScript) running in the Electron main process.**
- Sonnet 4.5 for routine turns, Opus 4.7 for "generate 3 variation plans + pick best" (worth the cost for iteration loop).
- `CLAUDE.md` + `/memory` for cross-session style memory — literally what it was built for.
- Subagents for variation loop: spawn 3 `Task`-tool subagents with different creative directions, parent scores outputs against learned style.
- Hooks: `SessionStart` to load style memory; `PostToolUse` on FFmpeg tool to validate output; custom file-watcher hook (chokidar) that fires `UserPromptSubmit` with "New clip detected: X" for proactive greeting.

**Tools via MCP:**
- Existing DaVinci Resolve MCP — plug in as-is.
- Wrap FFmpeg as local MCP server (10 lines with TS SDK) so it's swappable.
- Gemini Files API: direct SDK call inside a custom tool — no benefit to MCP-wrapping a single-provider API.

**UI: Vercel AI SDK in the Electron renderer.**
- `useChat` for chat pane, streaming from main process over IPC bridged to HTTP transport.
- Stream tool-call progress ("Analyzing clip… Rendering variation 2/3…") using custom data parts.

**State/persistence: SQLite via `better-sqlite3`** for:
- Session index (pointer to Claude SDK transcripts on disk)
- File-watcher state (seen files, last-suggested-edit timestamps)
- Style embeddings (if "learn from past edits" loop added later)

**Why not LangGraph.** Don't need graph-level control flow — Claude SDK's agent loop + subagents give us variations-and-pick. LangGraph would double surface area for a debugger we don't need. Revisit only if pipeline becomes a DAG with 5+ decision points.

**Why not OpenAI Agents SDK.** Weaker filesystem + memory story; lose Opus-level planning quality on creative tasks. Handoffs aren't the primary abstraction.

**File watching.** Chokidar in Electron main → debounce → push event into Claude SDK session via `query()` with synthetic user message. Don't do this inside agent loop; keep watcher as separate process that nudges agent.

**Cost profile.** With prompt caching: ~$0.10–0.50 per edit session on Sonnet 4.5, $1–3 if routing variation generation through Opus 4.7. Local-only except LLM calls.

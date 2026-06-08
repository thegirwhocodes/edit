# Research 5 — How Builders Actually Construct AI Agents (2026)

A practitioner's chapter for Ed.it's architecture planning.

## 1. The ReAct Loop and Its Evolution

### Origins and why it stuck

ReAct (Yao et al., 2022, ICLR 2023) is the unglamorous scaffold under almost every agent shipping today. The original insight: interleave a **Thought** (free-form reasoning), an **Action** (structured tool call), and an **Observation** (tool return value) in a rolling transcript, and the model's reasoning stays grounded in real-world feedback instead of hallucinating. Every turn, append the new `Observation` to context and let the model emit the next `Thought/Action`. Terminal action halts the loop.

By 2026 the literal `Thought:` / `Action:` / `Observation:` format is nearly extinct in production — the pattern got absorbed into native tool-calling, where "Thought" is the assistant's text turn, "Action" is a `tool_use` block, "Observation" is a `tool_result` block. Skeleton is identical. Strip any agent framework down, you find the ReAct while-loop.

### Evolution tree

**ReWOO (2023)** decoupled planning from execution. Planner writes whole tool-call DAG upfront with placeholders (`#E1`, `#E2`) referencing earlier observations, executor runs them, solver writes final answer. Saved tokens, collapsed when a tool failed mid-plan. Useful pattern for batchable subtasks.

**Reflexion (Shinn et al., 2023)** added verbal self-critique memory. After a trajectory, model writes natural-language "lesson" into episodic buffer, retries with lesson prepended. Quality gains real but task-dependent; most shipped agents don't run full Reflexion, they steal the *idea* — appending a post-error reflection line into the next loop iteration.

**Tree of Thoughts (ToT)** branches on each reasoning step, scores, prunes, explores. Expensive. In 2026 you see ToT-shaped ideas in research agents (Deep Research, o3-pro) as *test-time compute scaling* — sampling multiple trajectories and voting/ranking — but not in latency-sensitive UX. For Ed.it: skip.

**Plan-and-Execute (LangChain, 2023)** is the practical heir. Dedicated planner LLM produces numbered plan; executor loops calling tools; "replanner" revisits plan if a step fails or yields surprising info. Pattern Devin, Manus, and Sana's deeper workflows use. 2026 consensus landed here.

### The 2026 consensus: plan → act → reflect → revise

Squint at Claude Code, Cursor Composer, Devin, Manus, OpenAI Agents SDK, all converge on:

1. **Plan** — lightweight reasoning turn (often implicit via extended thinking tokens) sketching approach. Sometimes TODO list in a scratchpad tool.
2. **Act** — one or more tool calls, often parallel when independent.
3. **Reflect** — after observations, short self-check: *did that work? is the goal closer?*
4. **Revise** — continue, replan, or ask user.

Crucial: in 2026 shipped agents, phases 1 and 3 are usually *not* separate LLM calls. Reasoning models (o4, Claude Sonnet 4.7 extended thinking, Gemini 2.5) fold them into hidden thinking tokens. Loop looks flat from outside — thought blocks, tool calls, results — but planning/reflecting happens inside the thinking budget.

### Where ReAct breaks down

1. **Long horizons.** 200-step trajectory overflows any context window. Devin hit this hard; fix was persistent external memory (a "notebook") plus aggressive context compaction.
2. **Multi-step tool chains with data dependencies.** When step 5 needs full output of step 3, and step 3 returned 50KB JSON, you pay for it on every subsequent turn. Fix: tools return *handles* (IDs), separate `read_handle` tool.
3. **Unbounded tool surface.** If model sees 80 tools, selection accuracy drops. Fix: hierarchical tool exposure (see §2).
4. **Reward hacking on termination.** Model will claim success to end the loop. Fix: verifier tool call or user confirmation gate.

### How modern frameworks implement it

LangGraph: cyclic state graph, `agent` node → `tools` node → conditional edge back to `agent` or `END`. Typed state dict threaded through; checkpointer snapshots after every node.

Claude Agent SDK: async iterator over a `Session`. Call `session.query()`, get stream of typed events (`AssistantMessageEvent`, `ToolUseEvent`, `ToolResultEvent`, `SessionEndEvent`). SDK internally runs while-loop, invokes registered tool handlers. Hides checkpointing behind session ID.

OpenAI Agents SDK: `Runner.run(agent, input)` loops until agent returns final output or hands off. Tracing baked in.

Under all of them, same twenty lines: while True, call LLM, if tool_use then execute tool and append result, else return.

## 2. Tool Use and Function Calling

### How it works at the API level

At the API, a "tool" is a **JSON Schema** description. Pass list of tools to model; model returns either normal text response or structured tool-call object. Three flavors dominate 2026:

**OpenAI function calling** (unified `tools` param on Responses API):
```json
{
  "type": "function",
  "name": "trim_clip",
  "description": "Trim a video clip to a time range.",
  "parameters": {
    "type": "object",
    "properties": {
      "clip_id": {"type": "string"},
      "start_s": {"type": "number"},
      "end_s": {"type": "number"}
    },
    "required": ["clip_id", "start_s", "end_s"]
  }
}
```
Model responds with `{"type": "function_call", "name": "trim_clip", "arguments": "{...}", "call_id": "call_abc"}`. Execute, reply with `{"type": "function_call_output", "call_id": "call_abc", "output": "..."}`.

**Anthropic tool_use blocks.** Tools passed as `{name, description, input_schema}`. Assistant message contains `tool_use` content block; reply with `user` message containing `tool_result` block referencing same `tool_use_id`. Tool results can be multimodal (image blocks, text blocks) — crucial for Ed.it since you'll want to return video thumbnails.

**Gemini function_declarations.** Similar shape, with ergonomic of automatic Python function introspection (`tools=[my_python_func]` builds schema for you). Gemini supports "compositional" mode where model plans multi-step tool use in one shot.

All three converged on **strict mode / JSON schema guided decoding** by 2025: model constrained at decode time to emit tokens conforming to your schema. Arguments-parse failures dropped from ~3% to <0.1%. Always turn strict mode on.

### Parallel vs sequential tool calls

All major providers support **parallel tool calls**: one assistant turn can emit N `tool_use` blocks, execute concurrently, return as N `tool_result` blocks in next user turn. Single biggest latency win for agents. Cursor's codebase search agent fires 5–10 grep/read calls in parallel.

Force sequential when later calls truly depend on earlier results. Force parallel when calls are independent — hint in tool description (`"Safe to call in parallel with other read tools."`).

For Ed.it: timeline reads, thumbnail generation, transcript fetches all parallelizable. Timeline *writes* must be sequential, queued.

### Tool call validation / retry loops

Strict mode catches schema violations, not semantic errors (bad clip IDs, out-of-range times). Pattern:

```python
def handle_tool_call(call):
    try:
        args = validate(call.arguments)
        return {"ok": True, "data": tool_fn(**args)}
    except ValidationError as e:
        return {"ok": False, "error": f"ValidationError: {e}. Hint: see schema."}
    except ToolError as e:
        return {"ok": False, "error": str(e), "suggestion": e.hint}
```
Return structured errors, not exceptions. LLM reads, fixes itself, retries. Cap retries at 3 to prevent loops.

### MCP as the 2026 interop standard

Model Context Protocol (Anthropic, open-sourced late 2024) is the USB-C of agent tooling. By Q1 2026 it's the default. MCP server exposes three primitives:

- **Tools** — functions model can call.
- **Resources** — files/URIs model can read (e.g. `file:///project/timeline.json`).
- **Prompts** — parameterized prompt templates users can trigger.

Wire protocol: JSON-RPC over stdio or HTTP/SSE. Any MCP-compliant host (Claude Desktop, Cursor, Zed, VS Code, Claude Code, Claude Agent SDK, OpenAI Agents SDK via adapter) can connect to any MCP server. For Ed.it: **write video-editing primitives as MCP server**. Get Claude Desktop integration, Cursor integration, your own desktop app integration from one codebase. Non-negotiable.

### Dynamic vs static tool sets

Static: fixed tool list in system prompt. Simple, cacheable, blows up at ~40 tools.
Dynamic: agent has meta-tool `search_tools(query)` or `load_toolkit(name)` that loads relevant subset. How Devin, Manus handle 200+ tools.

Rule of thumb: under 20 tools, static. 20–50, group into logical "modes" (editing, export) and swap. 50+, dynamic loading.

### Streaming tool calls

Modern APIs stream tool call as delta-encoded JSON. Render `"Calling trim_clip(clip_id: c_01, start_s: 12.5, end_s: ..."` as it arrives. Users see intent before execution. Vercel AI SDK's `streamText` with `onToolCall` / `onToolResult` hooks handles this in React.

### Safety: sandboxing, permission prompts, audit logs

Three layers, non-optional for desktop agent:

1. **Sandboxing** — tools touching filesystem / spawning processes run in constrained env. On macOS: App Sandbox entitlements + bookmark-scoped file access. Only grant directories user explicitly picked.
2. **Permission prompts** — tools marked `destructive: true` (delete clip, overwrite export) interrupt and ask. Claude Code's model is good: per-tool, per-session, with "always allow."
3. **Audit logs** — every tool call with args, result, timestamp, session ID. Write to local SQLite. Non-negotiable for debugging and eventual "undo."

## 3. Memory Systems (Agent-Building Angle)

- **Short-term** is context window. Don't fight it; structure it. System prompt → stable memory (pinned) → scratchpad → recent turns.
- **Working memory / scratchpad** is dedicated section agent edits via `scratchpad.write(section, content)` and reads by reference. Claude Code's TODO list is this.
- **Long-term** splits into semantic (vector DB: embeddings of past edits, preferences) and relational (SQLite: project metadata, clips, exports). Vectors for fuzzy recall; SQL for exact queries. Always both.

### MemGPT / Letta self-editing memory

MemGPT frames memory itself as tools: `core_memory_append`, `core_memory_replace`, `archival_memory_insert`, `archival_memory_search`, `conversation_search`. Agent manages own context, paging in/out. Powerful for unbounded-lifetime agents. For Ed.it's session-scoped work, overkill — use simpler scheme with fixed "core memory" block and separate search tool for older sessions.

### Memory as tool calls

Dominant 2026 pattern. Rather than auto-RAG every turn (pollutes context unpredictably), expose:
- `memory.recall(query: str, k: int)` — returns relevant snippets.
- `memory.write(kind: str, content: str)` — writes durable fact.
- `memory.pin(id: str)` — keeps something in-context.

Model decides when to remember and recall. More tokens but wildly more predictable than black-box retrieval.

### Always-load core vs query-on-demand

Core (always loaded): user's name, brand voice, current project goal, coarse state, preferences. Target: <500 tokens.
Query-on-demand: past session summaries, specific clip metadata, style references. Via tool calls.

Failure mode to avoid: stuffing "helpful context" into system prompt that isn't needed 90% of the time. Every token in system prompt is paid for every turn.

## 4. Orchestration Patterns

### Single agent with many tools

The default. One loop, one LLM, a tool belt. Claude Code, Cursor, v0, Devin's worker all single-agent at core. 80% of production agents in 2026 are this. Opinion swung back toward "one smart agent > five dumb agents" after 2024 multi-agent craze produced brittle, hard-to-debug systems.

For Ed.it: **start here**. One Ed.it agent with 20ish tools.

### Multi-agent: orchestrator + workers

Tasks genuinely parallelizable and specialized, orchestrator dispatches subtasks to workers with own context. Anthropic's "Building Effective Agents" post calls this **orchestrator-workers**. Good fit: generating 10 variant edits of the same clip in parallel, each worker experimenting independently.

### Router + specialists

Lightweight router (often Haiku-tier) classifies request, dispatches to specialist. Good for breadth-heavy products ("edit mode", "export mode", "analyze mode"). Watch out: router becomes bottleneck; mis-routes are recovery-expensive.

### Handoff pattern (OpenAI Agents SDK)

Handoff is a tool call that transfers control to another agent, passing conversation state. `agent = Agent(..., handoffs=[other_agent])`. Clean for triage→specialist (support bot → billing bot). Less clean for iterative collaboration — handoffs are one-way.

### Graph-based (LangGraph)

Explicit state graph. Nodes = functions (LLM call or tool); edges can be conditional; cycles allowed; every transition updates typed state; **checkpointer** persists state after every node for resume/branch/time-travel. Powerful, explicit, testable; verbose for simple agents but a win once you have branching, HITL, or durable execution.

```python
builder = StateGraph(AgentState)
builder.add_node("agent", call_model)
builder.add_node("tools", ToolNode(tools))
builder.add_conditional_edges("agent", route, {"tools": "tools", "end": END})
builder.add_edge("tools", "agent")
graph = builder.compile(checkpointer=SqliteSaver(...))
```

### Swarm

Multiple peer agents communicating via shared blackboard. OpenAI's Swarm (2024) popularized it, got folded into Agents SDK handoff. Rarely right answer in 2026; debugging nightmare, emergent behavior rarely what you wanted.

### Decision rules

- **Single:** default, always try first.
- **Orchestrator + workers:** parallelizable, bounded subtasks.
- **Router + specialists:** distinct workflows, little shared state.
- **Handoff:** escalation / triage.
- **Graph:** HITL gates, durable long-running jobs, complex branching, replay/debugging need.
- **Swarm:** almost never.

**Ed.it recommendation:** single agent for interactive editing loop, orchestrator+workers for "generate 5 variants" feature, LangGraph-style checkpointing underneath for durability.

## 5. Planning

### Implicit (most agents)

LLM thinks step-by-step inline via extended thinking tokens or natural prose, then acts. Reasoning models (o-series, Claude extended thinking, Gemini thinking) made this dramatically better — model plans in hidden tokens, emits concise surface message, calls tools. Dominant 2026 pattern for interactive agents.

### Explicit planners

Dedicated planner LLM call produces structured plan (JSON or markdown TODO) executor loop consumes. Used when:
- Plan should be user-visible and approvable (Cursor Composer shows a plan first).
- Plan spans many steps, avoid re-deriving.
- Want multiple workers against plan in parallel.

```python
plan = planner_llm(goal, context)
scratchpad.write("plan", plan)
for step in plan:
    result = executor_agent(step, scratchpad)
    if result.failed:
        plan = replanner_llm(goal, scratchpad, failure=result.error)
```

### Plan storage and revision

Store plan in scratchpad tool agent can read/edit. On failure, **replanner** takes original goal + current partial plan + failure reason, returns new plan starting from failure point. Never throw away work already done — feed completed step outputs to replanner.

### HTN making a comeback

Hierarchical Task Networks (classical AI planning) having minor renaissance in 2026 for bounded domains. Predefine "methods" that decompose high-level tasks into subtasks, let LLM *choose which method to apply*. For a video editor, natural fit: "make a 30-second Reel" has a known method (hook → 3 beats → CTA); LLM's job is to fill slots. Not pure-HTN — **LLM-selected templates** — dramatically stabilizes quality for well-understood workflows. Worth baking into Ed.it for common content formats.

## 6. Reflection and Self-Correction

### Reflexion

Write down what went wrong in natural language, feed back on retry. Works when task has clear success signal (tests pass, output validates). For creative tasks, signal is fuzzy and Reflexion degrades into self-flattery. Skip for Ed.it main loop; keep for compile-style tasks ("export video" failed with ffmpeg error).

### Self-consistency

Generate N trajectories, pick best by majority vote or LLM judgment. Expensive. Reserved for high-stakes single-shot tasks. Not useful for Ed.it.

### Critic / actor

Actor LLM produces; critic LLM scores and sends revision notes; loop until critic approves or cap hit. Good for text quality (captions, hook lines). For Ed.it: use for caption generation and thumbnail copy; don't use for timeline edit itself.

### LLM-as-judge

Separate LLM call scores output against rubric. Excellent for eval (§10), less reliable as live gate. Known biases: position bias (favors first), verbosity bias (favors longer), self-preference. Mitigations: randomize order, pairwise comparisons, different model as judge than actor.

### When reflection adds value

Add when (a) failures are verifiable, (b) retries cheap, (c) cost of bad answer high. Skip for interactive turns where user can say "no, try again" — they are the reflector.

## 7. Human-in-the-Loop

### Interrupt + resume

Foundational: agent pauses mid-loop, surfaces question, waits, resumes with full context intact. LangGraph: `interrupt()` inside a node raises special exception the runtime catches, persists state via checkpointer, returns control. Resume: `graph.invoke(Command(resume=user_input), config)`. Under the hood: serialized state + typed resume message.

### Approval gates

Wrap destructive tools in permission layer: (a) check policy (auto-allowed? always ask?), (b) if asking, yield `approval_request` event to UI, (c) wait for response, (d) execute or skip. Implement **outside the agent** so agent's prompt doesn't need to know — tool just blocks.

### UI patterns that work

- **Cursor's diff-based Accept/Reject.** Best pattern ever for code agents. Translates to Ed.it: every proposed edit is a reversible diff on the timeline; user sees before/after previews, taps Accept/Reject/Modify.
- **Claude Code's inline permission prompts.** Modal, "yes/no/always."
- **v0/Bolt's preview-first.** Agent produces output, user sees live preview, iterates via chat. Ed.it's primary UX should be this.
- **Comet/Operator's "takeover" button.** Agent drives; user can grab wheel anytime. Ed.it: "pause agent, direct-manipulate timeline, resume."

Unifying principle: **every agent action should be reversible or approvable**. More reversible → less you need to approve.

## 8. State and Durability

### Stateful vs stateless

Stateless: conversation is only state; each turn replays from scratch. Simple, ugly at scale — pay for full transcript every turn (prompt caching helps).

Stateful: persisted state object (dict of facts, scratchpad, TODO, retrieval caches) separate from transcript, updated between turns. Required for non-trivial agents.

2026 default: **stateful with message-log as one piece of state**. LangGraph, Agent SDK sessions, OpenAI stored responses all do this.

### Checkpointing

Snapshot state to disk after every meaningful transition. On crash or user-resume, load last checkpoint. LangGraph's `SqliteSaver` / `PostgresSaver`; Claude Agent SDK persists per-session automatically.

For desktop apps, SQLite. One row per checkpoint, JSON-serialized state, indexed by `(session_id, step_id)`. Keep last N per session for time-travel.

### Temporal-style durable execution

Temporal (+ LLM-native cousins Inngest Agent Kit, Restate, DBOS) treats every step as durable, idempotent activity. If worker crashes mid-step, platform replays from last completed step. For agents: **if user's laptop sleeps mid-export, resuming next day continues from exactly where stopped**. Heavyweight for desktop app, but pattern — deterministic replay of recorded trace — worth stealing. Implementation: record every tool-call input and output; on resume, replay recorded outputs instead of re-executing.

### Replay and time-travel debugging

Given a recorded trace, replay with different model, prompt, or tool implementation, see what changes. LangSmith, Braintrust, Claude Agent SDK's session export all support this. Single most important debugging affordance for agents. Build in from day one — structured trace events, persisted, replayable.

### Session persistence

- **Claude Agent SDK:** sessions durable by default; resume via `session_id`.
- **OpenAI Responses API:** `previous_response_id` chains turns server-side, caches context.
- **Gemini:** session objects in SDK; server-side caching via `cached_content`.

## 9. Streaming and UI

### SSE streaming

Every major provider streams via Server-Sent Events. Events: text deltas, reasoning-token deltas (thinking models), tool_use start/delta/stop, tool_result, message_stop, usage.

Render text the moment it arrives. Render tool calls as they stream — `trim_clip(clip_id: "c_01", ...)` — so users see intent immediately. For thinking models, show collapsed "Thinking..." widget with summary; let users expand.

### Vercel AI SDK (dominant in web UIs)

`streamText({ model, messages, tools })` returns async iterable of typed events; `useChat` / `useAssistant` React hooks wire to components. v4 supports tool-call streaming, MCP clients, multi-step loops (`maxSteps`). For Ed.it settings/onboarding panels, right choice.

### Rendering tool calls live

Each tool call is UI element with three states: *pending* (args streaming in, skeleton), *running* (args finalized, spinner, start timestamp), *done* (result shown, duration, inspect). Cursor + Claude Code both do this well. For Ed.it: every tool call touching timeline should have visual hook — clip being edited highlights as tool runs.

### Visible reasoning as trust builder

Users trust agents more when they see reasoning. Don't dump full thinking trace; summarize. Claude Code: live TODO list the agent edits. Cursor: expandable "thinking" block. Ed.it: running natural-language log: *"Watching the clip... detecting low-energy section at 00:12–00:17... trimming."*

## 10. Evaluation and Testing

### Unit tests for agents

Hard because stochastic. Patterns:
- **Seeded runs.** Some providers accept seed; combined with temp 0, near-determinism. Good for regression.
- **Schema tests.** Assert tool calls validate, args in-range, no forbidden tools. Deterministic.
- **Behavioral assertions via LLM-as-judge.** "Given this trace, does final output satisfy rubric X?" Stochastic but aggregated.

### Eval harnesses

- **LangSmith** — dataset management, LLM-as-judge, regression tracking, trace UI. Dominant 2026.
- **Braintrust** — similar scope, better DX for non-LangChain, strong TS support.
- **Inspect AI** (UK AISI) — favored for safety/capability evals.
- **OpenAI Evals** / **Anthropic's open eval framework** — provider-native, cheap, locked in.

### Golden task sets

30–100 representative tasks with known-good outputs or behaviors. Run every change against them. For Ed.it: 50 real editing prompts ("make this 30s with captions", "cut the ums", "add hook in first 3s"), each with reference trace and acceptance criteria (duration ±1s, captions present, no dead air >0.5s).

### LLM-as-judge evals

For creative quality, can't unit-test. Judge LLM with detailed rubric, pairwise comparison ("A or B, which better achieves goal?"). Track win rate against baseline. Don't over-trust absolute scores; trust relative movement.

### Trace-based debugging

Every production agent call emits structured trace (OpenTelemetry semantic conventions for GenAI finalized 2025). Store traces, search by session, filter by error, drill into tool calls. User reports "it did something weird" → pull trace, reproduce.

## 11. Cost and Latency

### Prompt caching

Anthropic and OpenAI (+ Gemini's implicit context cache) cache prefix tokens for 5–60 minutes, charging ~10% of normal input cost on cache hits. Single biggest cost lever for agents. Rules:
- Stable content (system prompt, tool definitions, core memory) *first*, mark cache boundary after.
- Keep stable prefix byte-identical across turns — any diff invalidates.
- Order: system → tools → core memory → [cache breakpoint] → conversation → [cache breakpoint] → latest turn.
- Anthropic allows up to 4 cache breakpoints; use them.

Savings for chatty agent: 60–85% cost reduction, 30–50% latency reduction on cached tokens.

### Model routing

Not every turn needs smart model:
- **Router / classifier:** Haiku / GPT-4o-mini / Gemini Flash. ~100× cheaper than frontier.
- **Tool execution turns:** mid-tier.
- **Planning, critical reasoning, final output:** frontier (Sonnet 4.7 / GPT-5 / Gemini 2.5 Pro).

Ed.it pattern: Sonnet 4.7 for main editing loop, Haiku for transcript chunking + metadata extraction, Haiku for router deciding whether a request needs full agent or simple utility.

### Batch API

Async work (overnight rendering 50 variants, bulk analysis): batch APIs give 50% discount, 24h turnaround. Perfect for Ed.it's "analyze my entire content folder" onboarding.

### Context window management

1. **Summarize old turns.** When transcript >80% of window, replace oldest N turns with summary.
2. **Tool result pruning.** Replace old tool results with `[redacted: tool_result id=...]` — agent rarely needs them verbatim after using once.
3. **External memory.** Move long content (transcripts, large JSON) to files/handles; agent reads on demand.
4. **Compaction.** Between major task boundaries, agent writes "session summary so far"; orchestrator restarts loop with summary + current goal. Claude Code does this automatically.

## 12. Production Gotchas

**Prompt injection defense.** Tools returning third-party content can inject instructions. Layered mitigations: (a) wrap tool outputs in clear delimiter + system-prompt-instruct model to treat wrapped content as data, not instructions; (b) for destructive actions, require confirmation from original user intent; (c) scan outputs for attack patterns; (d) highest-risk flows, separate "guard" LLM reviews proposed actions before execution. None bulletproof. Assume leakage, limit blast radius.

**Infinite loops.** Cap iterations (hard 20–50), cap per-tool retries (3), detect no-progress cycles (same tool call with same args twice → break, ask user). Log + alert on cap hits.

**Tool misuse / hallucinated tool calls.** Strict mode prevents schema hallucination; semantic validation catches bad IDs; "tools_used" allowlist per agent prevents calling tools it shouldn't. If agent calls non-existent tool, return structured error listing valid tools.

**Rate limits.** Exponential backoff + jitter, surface rate-limit state to UI ("slowed down, retrying..."), queue non-urgent calls. Track per-minute spend for surprise bills.

**Error handling.** Every tool returns `{ok: bool, data?, error?, retriable?}`. Agent sees error, decides. Unrecoverable surface to user with context.

**Token budget overruns.** Track per session; warn at 70%, force compaction at 85%, hard cap at 95% with notice. Users hate surprise "conversation too long" errors mid-edit.

**Context overflow.** Compaction (above). Never accept user-pasted unbounded content; chunk + summarize on ingress.

## 13. Real-World Patterns

**Cursor / Claude Code** — single-agent, massive tool belt (read, write, grep, bash, edit, todo, web), aggressive parallel tool calls, diff-based HITL, plan-first Composer mode. Key for Ed.it: tool set should mirror user's primitive actions (read clip, trim, caption, export) so agent's traces are legible as user's own workflow. Weakness: ambiguous multi-file edits cascade; recovery UX manual.

**Devin** — long-horizon planner-executor with "notebook" for persistent memory, browser + VSCode + shell tools, sandboxed cloud VMs per task. Strong autonomous, weak interactive. Pattern to steal: sandboxed per-task workspace with full env control. Ed.it: each project is own sandboxed workspace with bookmark-scoped file access.

**Browser agents (Browser Use, Operator, Comet)** — vision + DOM hybrid: agent gets screenshot AND structured accessibility tree, tool calls are `click(x,y)`, `type(text)`, `scroll(dir)`. Big lesson: **structured representation of UI state beats raw pixels**. Ed.it: agent sees structured timeline representation (JSON of clips, markers, tracks) alongside thumbnail previews, never raw pixel frames alone.

**Voice agents (Retell, Vapi, ElevenLabs)** — sub-second latency drives architecture: streaming STT, streaming LLM, streaming TTS, interrupt handling. Tool-use pattern: "one tool per turn, fast." Irrelevant to Ed.it's loop but worth knowing if you add voice ("cut the last sentence").

**Sana / Glean / Dust** — knowledge workspace agents: single-agent on top of deep retrieval layer; retrieval quality dwarfs agent sophistication. Pattern: **retrieval over user's content library matters more than agent framework**. Invest in indexing clips, transcripts, past edits, brand assets well.

**All do well:** reversible actions, visible reasoning, fast first tokens, graceful errors.
**All do poorly:** long-running background tasks (notifications half-baked), cross-session memory of user style (mostly absent), true multi-modal grounding (still text-centric).

## 14. Frameworks Snapshot

**Claude Agent SDK** (Python + TS, 2025, Anthropic) — new default for ops-heavy agents. Built on Claude Code runtime: sessions, durable state, native MCP, hook system, subagent pattern. Claude-first agent → start here. **For Ed.it: recommended primary framework.**

**OpenAI Agents SDK** (Python + TS, GA 2025) — handoff-centric, tracing-first, Responses-API native. Clean DX, strong for triage/routing. Use if OpenAI-first.

**LangGraph** — graph + state + checkpointer. Explicit, powerful, verbose. Best for HITL gates, durable long-running jobs, complex branching. Production choice for explicit workflows you can reason about. Underpins LangSmith.

**Vercel AI SDK** — UI-first. Not full agent framework; pair with Agent SDK or LangGraph on server. Dominant for web UIs and Next.js.

**Mastra** (TS, 2024–) — full-stack TS agent framework: workflows, memory, RAG, evals, dev UI. Nice for all-TypeScript stack, batteries-included without LangGraph verbosity.

**Inngest Agent Kit** — durable execution for agents. If already on Inngest for background jobs.

**AutoGPT / BabyAGI** — historical. 2023 "autonomous agent" moment. Conceptual importance; not production today.

## 15. The "From Scratch" Path

Strip everything away and an agent is:

```python
messages = [{"role": "system", "content": SYSTEM_PROMPT}]
messages.append({"role": "user", "content": user_input})

for step in range(MAX_STEPS):
    resp = llm.create(model=MODEL, messages=messages, tools=TOOLS)
    messages.append(resp.message)

    if not resp.tool_calls:
        return resp.message.content

    tool_results = []
    for call in resp.tool_calls:
        try:
            result = TOOL_REGISTRY[call.name](**json.loads(call.arguments))
            tool_results.append({"tool_call_id": call.id, "content": result})
        except Exception as e:
            tool_results.append({"tool_call_id": call.id, "content": f"ERROR: {e}"})

    messages.append({"role": "tool", "content": tool_results})

raise MaxStepsExceeded()
```

That's an agent. Everything else — LangGraph, Agent SDKs, orchestration libs — is scaffolding around this loop. Scaffolding matters (checkpointing, tracing, HITL, multi-agent, evals), but not magic.

**When from-scratch is right:**
- Total control over loop (custom retry, custom context management).
- Narrow, well-defined use case where framework overhead outweighs benefits.
- Zero dependencies, want to understand every line.
- Building prototype, don't yet know which abstractions you need.

**When you outgrow it:** moment you need any of — checkpointing, HITL, multi-agent, parallel tool calls with aggregation, eval harness, tracing — grab a framework. Don't reinvent.

### Recommendation for Ed.it

**Build core editing loop on Claude Agent SDK.** Get sessions, hooks, native MCP, good defaults. Expose Ed.it's editing primitives as **MCP server** so Claude Desktop, Cursor, and your own app can all call them — single highest-leverage architecture choice in 2026. Use LangGraph (or Agent SDK's subagent pattern) for durable background jobs. Use Vercel AI SDK for any web surface. Wire LangSmith or Braintrust for evals from day one; build 50-task golden set before shipping. Sonnet 4.7 with extended thinking for main loop, Haiku for routing + utility turns. Cache aggressively — tool definitions and system prompt must be stable and prefix-cached. Every tool call logged to SQLite; every session checkpointed; every destructive action approval-gated.

Pattern you're aiming for: **Cursor-for-video** — single, smart, single-agent loop where every action is visible reversible diff on timeline, user always one tap from grabbing the wheel.

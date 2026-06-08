# Research 4 — Multi-Agent & Orchestration (2026)

For Ed.it, a desktop AI video editor (Electron + Python + Claude Agent SDK). Sibling docs: 01 frameworks, 02 agent loops, 03 tools/MCP. Written Jan 2026.

## 1. The honest tradeoff: single agent vs. multi-agent

**Default to one agent with good tools.** Multi-agent is fashionable but expensive. Every additional agent adds:

- **Latency.** Each subagent round trip is a full prompt + generation. A 3-way parallel branch is only as fast as the slowest branch. A serial handoff is strictly additive.
- **Tokens.** Each subagent reloads a system prompt, often a subset of context, and produces its own output. A two-hop handoff can 3-4x total token spend over one agent.
- **Coordination bugs.** Hallucinated sibling results, stale state, dropped tool outputs, "I already did that" loops. The bug surface grows combinatorially.
- **Debugging cost.** You now need a trace viewer, not just a log file.

Multi-agent earns its keep in exactly four situations:

1. **Parallelism.** Genuine embarrassingly-parallel work — three variations at once, six files analyzed in parallel. Wall-clock savings are real and user-visible.
2. **Fresh context per task.** Research subagents that go off, read 40 files, return a 500-token summary. The parent never sees the 80k tokens of raw research. This is the killer use case for Claude Agent SDK's `Task` tool.
3. **Specialized system prompts.** A "safety reviewer" prompt that would pollute a "creative generator" prompt if stuffed into one agent. Separation of concerns via separate prompts.
4. **Different model tiers per role.** Haiku for cheap classification, Sonnet for work, Opus for planning. Impossible to do cleanly in one agent loop.

If none of those apply, stay single-agent. A reader who built a prototype and is asking "should I go multi-agent now?" — the answer is almost always *not yet*.

## 2. Orchestrator-worker (Claude Agent SDK `Task` tool)

One **coordinator** agent with a small set of high-level tools, one of which dispatches **worker subagents** with their own tool sets and prompts. Workers return a summary; the coordinator decides what to do next.

In Claude Agent SDK, the built-in `Task` tool does exactly this. The parent invokes `Task(subagent_type="researcher", prompt="...")` and the SDK spawns a fresh context window running the subagent's system prompt and tool set. When the subagent terminates (stop reason, `Stop` hook, or token limit), its final message is returned to the parent as a tool result. The parent continues its own loop.

Key properties:

- **Fresh context by default.** Subagents do NOT see the parent's conversation. This is correct for research (don't bias) and wrong when you need state (the subagent rediscovers what the parent already knew). You can pass state in via the prompt argument — but if the prompt gets long, you've lost the point.
- **Parent waits.** The parent's loop is paused until the subagent returns. True fire-and-forget is not the default — you'd build it yourself by spawning a separate `query()` session and not awaiting.
- **Parallel subagents.** Issue multiple `Task` calls in one assistant turn; the SDK runs them concurrently. This is how "3 variations in parallel" is implemented.
- **No nesting by default.** Subagents can't spawn subagents unless you give them the `Task` tool too. Don't. Chains of delegation are where telephone-game bugs live.

```python
# Orchestrator pattern — Claude Agent SDK (Python)
from claude_agent_sdk import query, ClaudeAgentOptions, AgentDefinition

options = ClaudeAgentOptions(
    agents={
        "variation_planner": AgentDefinition(
            description="Plans one edit variation with a specific creative direction.",
            prompt=(
                "You are a video-editing planner. Given footage analysis and a "
                "creative direction (safe/stretch/wild), output a JSON plan with "
                "cuts, transitions, and music cues. Do not render."
            ),
            tools=["Read", "Grep"],  # no FFmpeg — planning only
            model="sonnet",
        ),
    },
    allowed_tools=["Task", "Read", "Bash"],
)

# Parent prompt: "Generate 3 variations with directions safe/stretch/wild,
# then score them and render the winner." Parent issues 3 parallel Task calls.
async for msg in query(prompt=brief, options=options):
    ...
```

For Ed.it this is the *only* multi-agent pattern we'll adopt in v1 — and only for variation generation (§8).

## 3. Handoff pattern (OpenAI Agents SDK)

Different shape. One agent is active at a time. Agent A decides to transfer control to Agent B by calling a `handoff` tool; the runner swaps B in as the new active agent and continues the same conversation (full history, or filtered by an `input_filter`).

```python
# Handoff pattern — OpenAI Agents SDK
from agents import Agent, Runner, handoff

renderer = Agent(
    name="Renderer",
    instructions="Execute an approved edit plan via FFmpeg. Do not re-plan.",
    tools=[ffmpeg_tool, davinci_tool],
)

planner = Agent(
    name="Planner",
    instructions="Plan edits. When plan is approved by user, hand off to Renderer.",
    tools=[analysis_tool],
    handoffs=[handoff(renderer)],
)

result = await Runner.run(planner, input=user_brief)
```

Contrast with orchestrator-worker:

| Aspect | Orchestrator-worker | Handoff |
| --- | --- | --- |
| Active agents | Parent + N children concurrently | Exactly one |
| Context sharing | Fresh child context (unless passed) | Full history transfers (or filtered) |
| Return | Child returns, parent resumes | No return — B is now in charge |
| Best for | Parallelism, isolation | Role-based routing (triage → specialist) |

Handoff is clean when the workflow is genuinely "one agent at a time, but a different one for each phase." For a creative loop where the planner wants the renderer's output back to judge it, handoff is the wrong shape — use orchestrator-worker.

## 4. Pipeline / chain

Deterministic DAG. Each node is an LLM (or tool) call. Edges are fixed or conditional on typed state. This is LangGraph's bread and butter; it's also what LangChain's old `Runnable` chains and even a hand-rolled `async def pipeline(x)` do.

```
analyze_clip  →  propose_plan  →  validate_plan  →  render  →  post_mortem
                                   │
                                   └── on fail → revise_plan ──┘  (cycle)
```

Not really "agentic" — the control flow is yours, the LLM is a node. But for many video-editor workflows this is actually the right abstraction:

- The steps are **known** and **stable**. You're not asking the model to decide *whether* to analyze before planning; it always does.
- You can **type the state** (Pydantic / Zod) so each node has a schema contract with the next.
- **Checkpointing is free** in LangGraph — interrupt at any node for HITL approval.

**Prefer a pipeline over an agent when the DAG doesn't change between runs.** Prefer an agent when the control flow depends on content ("if clip is talking-head, skip music-bed analysis; if not, don't"). The Ed.it "analyze → plan → render" path is really a pipeline; trying to make it agentic buys nothing.

## 5. Swarm / debate / consensus

N agents independently solve the same problem; a judge (or voting rule) picks the best answer. Variants: Society-of-Mind debate, self-consistency with an LLM judge, LLM-as-a-jury.

Where it works:

- Hard-reasoning benchmarks (math, complex code). Ensemble + judge beats single-sample on MMLU/HumanEval-style tasks.
- Offline, research-grade evaluation where cost and latency are irrelevant.

Where it doesn't:

- **Time-sensitive user-facing apps.** Users don't want to wait 45s for a five-agent debate when one agent answers in 8s.
- Open-ended creative tasks where "best" isn't measurable — the judge hallucinates a winner.

Variation generation (§8) looks like a swarm but is not — the three planners have **different instructions**, not the same. That's targeted parallelism, not debate. Skip true swarm/debate for Ed.it.

AutoGen's `GroupChat` is worth naming here: N agents take turns, a "manager" picks who speaks next. Great for research demos of emergent behavior; brittle in production because turn order is itself an LLM decision that goes off the rails.

## 6. Model tiering by role

The cost-quality math is real. As of Jan 2026, Anthropic list prices per million input/output tokens (with prompt caching making input near-free on hot paths):

- **Haiku 4.5** — ~$1 / $5
- **Sonnet 4.5** — ~$3 / $15
- **Opus 4.7** — ~$15 / $75

A single 20-turn editing session on Opus-only costs 5x the Sonnet version for maybe 10-15% quality lift on non-planning turns. Tiering:

- **Haiku** — salience judging ("is this clip worth analyzing?"), tool-argument formatting, classification, short summaries, the `PreToolUse` hook's "should I approve this?" question. Anything where the model is a pattern-matcher.
- **Sonnet** — the default worker. Tool use, code gen, plan execution, renderer agent. 90% of turns.
- **Opus** — plan generation, critique/judge roles, the "pick best of three variations" step, ambiguous creative decisions. Few turns, high leverage.

Rule of thumb: **route by decision value, not task type.** A one-shot decision that steers the next 20 turns is worth Opus. A tool-argument shuffle is worth Haiku. Using Opus everywhere burns money on turns where Sonnet would be indistinguishable.

Claude Agent SDK's `AgentDefinition.model` field plus `ClaudeAgentOptions.model` make this per-subagent assignment a one-line change.

## 7. Shared state between agents

Three options, in order of increasing messiness:

**(a) Tool-call arguments.** Parent passes state into the subagent's prompt / tool arguments. Subagent returns its result as the tool call's return value. Clean, bounded, type-checkable. Works great until the state is too big to shove through a prompt.

**(b) Shared filesystem / DB.** Agents read and write files or rows. Scales to any size. Now you have a concurrency problem, a schema problem, and a "who owns this file" problem. Also: without locking, two subagents can clobber each other's writes.

**(c) Shared memory store with explicit read/write ops.** A key-value store (LangGraph's `Store`, Redis, SQLite) with agents calling `memory.get(k)` and `memory.put(k, v)` as tools. Middle ground: bounded ops, no raw file fights, but you design the schema.

**Recommendation for Ed.it: (a) for the variation loop, (b) for session-level state, never (c) in v1.**

- Variation subagents receive analysis JSON as a prompt argument, return a plan JSON. That's (a). Clean.
- Session-level state (style memory, file-watcher seen-list, SQLite session index) lives on disk and is read by the parent agent via normal `Read` / SQL tools. That's (b), but there's only one writer (the parent), so no concurrency.
- A bespoke `memory.put` tool layer is overbuilding for v1. Add only if we end up with 3+ long-running agents sharing mutable state.

## 8. Concrete multi-agent patterns for Ed.it

### 8a. Variation generation — the one clear win

Parent agent has footage analysis in context. Spawns three `Task` subagents in parallel, each with a different creative direction:

- `planner_safe` — conservative cuts, familiar structure.
- `planner_stretch` — one unconventional choice (audio-led cut, unexpected B-roll).
- `planner_wild` — break a rule on purpose.

Each returns a plan JSON. Parent then calls a **judge** turn (Opus, fresh-ish context, just the three plans + user's learned style memory) that scores and picks one. User sees three thumbnails; the picked one is rendered first, others held in reserve.

Shape: 1 parent (Sonnet) + 3 parallel Task subagents (Sonnet) + 1 judge turn (Opus, same parent loop, not a subagent). Wall clock ~= single-plan time because the three planners run concurrently. Total cost ~3.5x single-plan, worth it for iteration quality.

### 8b. Analyze → plan → render

Don't multi-agent this. It's a pipeline with three tools the single agent calls in order. Adding handoffs or subagents here adds latency and buys nothing — the control flow is linear and the context all fits.

### 8c. Style critic loop

Tempting to have a `Generator` agent and a `Critic` agent ping-pong. Don't, usually.

Same agent with two **role prompts** (switch via a turn-local system message or just "now critique what you just produced") wins because:

- Shared context — the critic doesn't need to re-read the generator's work.
- Cheaper — no handoff round trip.
- Simpler trace — one timeline.

Split into two agents *only* if the critic needs tools or prompt the generator shouldn't have (e.g., critic reads a 5000-token style rubric; generator doesn't need it polluting its context). Then a Task-subagent critic is correct.

### 8d. Proactive file-watcher daemon

Chokidar process watches `~/Movies/Footage/`. On a new clip, it pushes a synthetic user message into the main agent's session ("New clip detected: `clip_042.mov`. 47s, 4K, outdoors."). Agent decides whether to proactively suggest an edit.

This is **not multi-agent.** It's event-driven. The watcher is a dumb process, not an LLM. Keep it that way — do not turn it into an agent that "decides" whether to nudge; the main agent can decide that on receipt. One brain.

## 9. Coordination anti-patterns

- **Sibling hallucination.** Subagent A produces `plan_A.json`. Subagent B, spawned in parallel with no access to A's output, writes "as agreed with A, we will…" in its own plan. Guard: never imply siblings to parallel subagents; merge in the parent.
- **Infinite delegation.** Parent delegates to child; child, given `Task`, delegates to grandchild; grandchild delegates back up. Guard: do not give subagents the `Task` tool unless you explicitly want a tree. Depth-limit it anyway.
- **Lost child state.** Parent forgets which subagent is doing what. Guard: parent maintains a small scratchpad ("Pending: plan_safe [task_id=…], plan_wild [task_id=…]") and updates on each return. Claude Agent SDK's `PostToolUse` hook can write this for you.
- **Telephone game.** Each handoff drops a little context. After four hops the last agent is optimizing for a garbled version of the user's intent. Guard: limit chains to depth 2; always transfer the original user message verbatim alongside any summary.
- **"I already did that" loops.** Agent B does work, hands back to A, A forgets B did it and re-dispatches. Guard: represent completion in structured state (a JSON field `variations_generated: 3`), not in prose.

## 10. Debugging multi-agent systems

It is 10x harder than single-agent debugging. Three reasons:

1. **Nonlinear timelines.** Two subagents running in parallel produce interleaved logs. Reading chronologically is misleading.
2. **Context divergence.** Each agent saw a different slice of state. "Why did B do X?" requires knowing exactly what B saw, which is not what A saw.
3. **Nondeterminism compounds.** One retry in agent A reshapes what B receives, which changes B's decision, which reshapes the judge.

What helps:

- **Unified trace view.** All agent turns on one timeline, colored by agent, with parent-child nesting. This is the single most valuable tool. Options:
  - **LangSmith** — excellent for LangGraph and anything emitting its trace format. Hierarchical runs, token costs, replay.
  - **Braintrust** — good for eval-heavy workflows; trace + eval in one UI.
  - **OTEL + Jaeger** — DIY but portable. Works if you instrument agent turns as spans.
  - **Anthropic's trace viewer** (platform) — good for Claude Agent SDK sessions.
  - **Claude Agent SDK session logs** — JSONL on disk, resumable. The primitive under everything else.
- **Deterministic replays.** Pin `temperature=0` and a fixed seed where supported. You won't get identical outputs but you'll get close enough to bisect.
- **Single-agent fallback mode.** Build a flag that collapses subagent calls into inline tool calls on one agent. When things go weird, flip the flag and see if the bug is in coordination or in the work itself.

## 11. Recommendation for Ed.it v1

**Start single-agent.** One Claude Agent SDK session, Sonnet 4.5, with the full tool set (Gemini analysis, FFmpeg, DaVinci MCP, filesystem). This is already a capable editor and cheaper to debug.

**Add subagents only for variation generation.** Three parallel `Task` planners + one Opus judge turn. This is the one place users *see* parallelism — three thumbnails appearing together vs. one thumbnail in a third of the time. Worth the complexity.

**Don't build handoff or swarm.** No OpenAI-style Agent-to-Agent transfers, no debate, no GroupChat. Ed.it doesn't have role-routing needs that warrant it.

**Revisit at v3.** If by then Ed.it has (a) a HITL approval flow with 3+ distinct human roles, (b) long-running research (e.g., "scan my 400-hour archive and propose a 10-minute reel"), or (c) multi-tenant agents running concurrently, reopen this doc. Until then: one brain, one timeline, good tools.

---

*Written with training knowledge through January 2026; web access was unavailable in this sandbox. Framework version numbers (Claude Agent SDK, OpenAI Agents SDK, LangGraph) and price figures reflect state as of that cutoff and may have drifted. No URLs fabricated — see sibling doc 01 for canonical doc links.*
